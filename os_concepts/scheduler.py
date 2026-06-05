# os_concepts/scheduler.py
# Request Scheduler simulator implementing FCFS, RR, Priority Queue, SJF, and MLFQ scheduling algorithms.

import time
from collections import deque
import random

class Request:
    def __init__(self, request_id, user_id, region, priority, cost_units, arrival_time):
        self.request_id = request_id
        self.user_id = user_id
        self.region = region
        self.priority = priority # 1 = low, 2 = medium, 3 = high (for priority queue)
        self.cost_units = cost_units # Simulated query execution time units (SJF)
        self.remaining_cost = cost_units
        self.arrival_time = arrival_time
        self.start_time = None
        self.completion_time = None
        self.waiting_time = 0
        self.turnaround_time = 0

class RequestScheduler:
    def __init__(self):
        pass

    def schedule_fcfs(self, requests):
        """First Come First Served Scheduling"""
        sorted_reqs = sorted(requests, key=lambda r: r.arrival_time)
        current_time = 0
        timeline = []
        
        for req in sorted_reqs:
            if current_time < req.arrival_time:
                current_time = req.arrival_time
            
            req.start_time = current_time
            # Simulate processing
            current_time += req.cost_units
            req.completion_time = current_time
            req.waiting_time = req.start_time - req.arrival_time
            req.turnaround_time = req.completion_time - req.arrival_time
            
            timeline.append({
                "request_id": req.request_id,
                "start": req.start_time,
                "end": req.completion_time,
                "user_id": req.user_id,
                "region": req.region
            })
            
        return sorted_reqs, timeline

    def schedule_sjf(self, requests):
        """Shortest Job First (Non-preemptive)"""
        sorted_by_arrival = sorted(requests, key=lambda r: r.arrival_time)
        current_time = 0
        timeline = []
        completed = []
        ready_queue = []
        
        i = 0
        n = len(requests)
        
        while len(completed) < n:
            # Load all arrived jobs into ready queue
            while i < n and sorted_by_arrival[i].arrival_time <= current_time:
                ready_queue.append(sorted_by_arrival[i])
                i += 1
                
            if not ready_queue:
                if i < n:
                    current_time = sorted_by_arrival[i].arrival_time
                    continue
                else:
                    break
                    
            # Sort ready queue by query cost (shortest job first)
            ready_queue.sort(key=lambda r: r.cost_units)
            req = ready_queue.pop(0)
            
            req.start_time = current_time
            current_time += req.cost_units
            req.completion_time = current_time
            req.waiting_time = req.start_time - req.arrival_time
            req.turnaround_time = req.completion_time - req.arrival_time
            completed.append(req)
            
            timeline.append({
                "request_id": req.request_id,
                "start": req.start_time,
                "end": req.completion_time,
                "user_id": req.user_id,
                "region": req.region
            })
            
        return completed, timeline

    def schedule_priority(self, requests):
        """Priority Scheduling (Non-preemptive, Higher Priority Number = Higher Priority)"""
        sorted_by_arrival = sorted(requests, key=lambda r: r.arrival_time)
        current_time = 0
        timeline = []
        completed = []
        ready_queue = []
        
        i = 0
        n = len(requests)
        
        while len(completed) < n:
            while i < n and sorted_by_arrival[i].arrival_time <= current_time:
                ready_queue.append(sorted_by_arrival[i])
                i += 1
                
            if not ready_queue:
                if i < n:
                    current_time = sorted_by_arrival[i].arrival_time
                    continue
                else:
                    break
                    
            # Sort by priority desc (high priority first), then by arrival asc
            ready_queue.sort(key=lambda r: (-r.priority, r.arrival_time))
            req = ready_queue.pop(0)
            
            req.start_time = current_time
            current_time += req.cost_units
            req.completion_time = current_time
            req.waiting_time = req.start_time - req.arrival_time
            req.turnaround_time = req.completion_time - req.arrival_time
            completed.append(req)
            
            timeline.append({
                "request_id": req.request_id,
                "start": req.start_time,
                "end": req.completion_time,
                "user_id": req.user_id,
                "region": req.region
            })
            
        return completed, timeline

    def schedule_rr(self, requests, quantum=4):
        """Round Robin Scheduling"""
        sorted_by_arrival = sorted(requests, key=lambda r: r.arrival_time)
        current_time = 0
        timeline = []
        completed = []
        ready_queue = deque()
        
        # Deep copy remaining costs
        for r in sorted_by_arrival:
            r.remaining_cost = r.cost_units
            
        i = 0
        n = len(requests)
        
        # Initialize
        if n > 0:
            current_time = sorted_by_arrival[0].arrival_time
            while i < n and sorted_by_arrival[i].arrival_time <= current_time:
                ready_queue.append(sorted_by_arrival[i])
                i += 1
                
        while ready_queue or i < n:
            if not ready_queue:
                current_time = sorted_by_arrival[i].arrival_time
                while i < n and sorted_by_arrival[i].arrival_time <= current_time:
                    ready_queue.append(sorted_by_arrival[i])
                    i += 1
                    
            req = ready_queue.popleft()
            
            if req.start_time is None:
                req.start_time = current_time
                
            exec_time = min(quantum, req.remaining_cost)
            timeline.append({
                "request_id": req.request_id,
                "start": current_time,
                "end": current_time + exec_time,
                "user_id": req.user_id,
                "region": req.region
            })
            
            current_time += exec_time
            req.remaining_cost -= exec_time
            
            # Load new arrivals during this execution quantum
            while i < n and sorted_by_arrival[i].arrival_time <= current_time:
                ready_queue.append(sorted_by_arrival[i])
                i += 1
                
            if req.remaining_cost > 0:
                # Put back in queue
                ready_queue.append(req)
            else:
                req.completion_time = current_time
                req.waiting_time = req.completion_time - req.arrival_time - req.cost_units
                req.turnaround_time = req.completion_time - req.arrival_time
                completed.append(req)
                
        return completed, timeline

    def schedule_mlfq(self, requests, quantums=[2, 6]):
        """Multilevel Feedback Queue Scheduling
        - Queue 0: RR with Quantum=2 (Highest Priority)
        - Queue 1: RR with Quantum=6 (Medium Priority)
        - Queue 2: FCFS (Lowest Priority)
        """
        sorted_by_arrival = sorted(requests, key=lambda r: r.arrival_time)
        current_time = 0
        timeline = []
        completed = []
        
        # Queues
        q0 = deque() # Q0: RR q=2
        q1 = deque() # Q1: RR q=6
        q2 = deque() # Q2: FCFS
        
        for r in sorted_by_arrival:
            r.remaining_cost = r.cost_units
            
        i = 0
        n = len(requests)
        
        if n > 0:
            current_time = sorted_by_arrival[0].arrival_time
            while i < n and sorted_by_arrival[i].arrival_time <= current_time:
                q0.append(sorted_by_arrival[i])
                i += 1
                
        while q0 or q1 or q2 or i < n:
            # Check for idle time
            if not q0 and not q1 and not q2:
                current_time = sorted_by_arrival[i].arrival_time
                while i < n and sorted_by_arrival[i].arrival_time <= current_time:
                    q0.append(sorted_by_arrival[i])
                    i += 1
            
            # Execute Q0 (Highest Priority)
            if q0:
                req = q0.popleft()
                if req.start_time is None:
                    req.start_time = current_time
                exec_time = min(quantums[0], req.remaining_cost)
                timeline.append({
                    "request_id": req.request_id,
                    "queue": 0,
                    "start": current_time,
                    "end": current_time + exec_time,
                    "user_id": req.user_id,
                    "region": req.region
                })
                current_time += exec_time
                req.remaining_cost -= exec_time
                
                # Check for new arrivals
                while i < n and sorted_by_arrival[i].arrival_time <= current_time:
                    q0.append(sorted_by_arrival[i])
                    i += 1
                    
                if req.remaining_cost > 0:
                    q1.append(req) # Demote to Q1
                else:
                    req.completion_time = current_time
                    req.waiting_time = req.completion_time - req.arrival_time - req.cost_units
                    req.turnaround_time = req.completion_time - req.arrival_time
                    completed.append(req)
                    
            # Execute Q1 (Medium Priority)
            elif q1:
                req = q1.popleft()
                if req.start_time is None:
                    req.start_time = current_time
                exec_time = min(quantums[1], req.remaining_cost)
                timeline.append({
                    "request_id": req.request_id,
                    "queue": 1,
                    "start": current_time,
                    "end": current_time + exec_time,
                    "user_id": req.user_id,
                    "region": req.region
                })
                current_time += exec_time
                req.remaining_cost -= exec_time
                
                # Check for new arrivals (which preempt Q1 since they go to Q0)
                new_arrivals = False
                while i < n and sorted_by_arrival[i].arrival_time <= current_time:
                    q0.append(sorted_by_arrival[i])
                    i += 1
                    new_arrivals = True
                    
                if req.remaining_cost > 0:
                    q2.append(req) # Demote to Q2
                else:
                    req.completion_time = current_time
                    req.waiting_time = req.completion_time - req.arrival_time - req.cost_units
                    req.turnaround_time = req.completion_time - req.arrival_time
                    completed.append(req)
                    
            # Execute Q2 (Lowest Priority - FCFS)
            elif q2:
                req = q2.popleft()
                if req.start_time is None:
                    req.start_time = current_time
                
                # We execute Q2 one unit at a time to allow preemption by new arrivals in Q0
                exec_time = 1
                timeline.append({
                    "request_id": req.request_id,
                    "queue": 2,
                    "start": current_time,
                    "end": current_time + exec_time,
                    "user_id": req.user_id,
                    "region": req.region
                })
                current_time += exec_time
                req.remaining_cost -= exec_time
                
                # Check for new arrivals
                new_arrivals = False
                while i < n and sorted_by_arrival[i].arrival_time <= current_time:
                    q0.append(sorted_by_arrival[i])
                    i += 1
                    new_arrivals = True
                    
                if req.remaining_cost > 0:
                    # Q2 stays in Q2
                    q2.appendleft(req)
                else:
                    req.completion_time = current_time
                    req.waiting_time = req.completion_time - req.arrival_time - req.cost_units
                    req.turnaround_time = req.completion_time - req.arrival_time
                    completed.append(req)
                    
        return completed, timeline

def generate_random_workload(count=15):
    requests = []
    current_arrival = 0
    for i in range(count):
        current_arrival += random.randint(0, 3)
        cost = random.choice([2, 4, 6, 8, 12, 16])
        priority = random.choice([1, 2, 3]) # 1=low, 2=med, 3=high
        region = random.choice(["us", "eu", "asia"])
        user_id = random.randint(1000, 9999)
        requests.append(Request(
            request_id=f"REQ-{i+1:02d}",
            user_id=user_id,
            region=region,
            priority=priority,
            cost_units=cost,
            arrival_time=current_arrival
        ))
    return requests
