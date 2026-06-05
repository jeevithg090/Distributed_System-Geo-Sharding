# os_concepts/work_queue.py
# Producer-Consumer Work Queue using Redis Lists as bounded buffer

import redis
import json
import time
import threading
import os

RUNNING_IN_DOCKER = os.path.exists('/.dockerenv') or os.environ.get('RUNNING_IN_DOCKER') == 'true'
REDIS_HOST = 'redis' if RUNNING_IN_DOCKER else 'localhost'
REDIS_PORT = 6379

class WorkQueue:
    def __init__(self, name="db-jobs", max_size=50):
        self.client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.queue_key = f"queue:{name}"
        self.max_size = max_size
        self.backpressure_events = 0
        self.processed_jobs = 0
        self.consumers = []
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

    def produce(self, job_data):
        """Enqueues a job (Producer). Applies backpressure if queue is full."""
        q_len = self.client.llen(self.queue_key)
        
        if q_len >= self.max_size:
            with self.lock:
                self.backpressure_events += 1
            # Simulate backpressure (block/wait or reject request)
            # For API, we'll reject or delay: return False to indicate backpressure
            return False, "BACKPRESSURE_LIMIT_EXCEEDED"

        serialized_job = json.dumps({
            "job_id": job_data.get("job_id"),
            "action": job_data.get("action"),
            "payload": job_data.get("payload"),
            "timestamp": time.time()
        })
        
        self.client.lpush(self.queue_key, serialized_job)
        return True, "JOB_ENQUEUED"

    def consume(self):
        """Dequeues and processes a job (Consumer). Blocks if queue is empty."""
        # BRPOP returns a tuple (key, value)
        job = self.client.brpop(self.queue_key, timeout=1)
        if job:
            _, val = job
            job_data = json.loads(val)
            # Simulate execution time
            time.sleep(0.05)
            with self.lock:
                self.processed_jobs += 1
            return job_data
        return None

    def start_consumers(self, num_threads=2):
        self.stop_event.clear()
        
        def worker():
            while not self.stop_event.is_set():
                try:
                    self.consume()
                except Exception as e:
                    print(f"WorkQueue consumer thread error: {e}")
                    time.sleep(0.5)

        for i in range(num_threads):
            t = threading.Thread(target=worker, name=f"WorkQueue-Consumer-{i+1}")
            t.daemon = True
            t.start()
            self.consumers.append(t)
            
        print(f"Started {num_threads} background worker threads for {self.queue_key}")

    def stop_consumers(self):
        self.stop_event.set()
        for t in self.consumers:
            t.join(timeout=1.0)
        self.consumers = []

    def get_stats(self):
        q_len = self.client.llen(self.queue_key)
        return {
            "queue_name": self.queue_key,
            "queue_depth": q_len,
            "max_capacity": self.max_size,
            "processed_jobs_total": self.processed_jobs,
            "backpressure_events_total": self.backpressure_events,
            "active_consumers": len(self.consumers),
            "backpressure_active": q_len >= self.max_size
        }
