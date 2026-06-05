# cache_benchmark.py
# Benchmark script using built-in urllib to compare database vs. Redis cache latency

import time
import urllib.request
import urllib.error
import json
import sys

API_URL = "http://localhost:8000"

def make_request(url, method="GET", data=None):
    req = urllib.request.Request(url, method=method)
    if data:
        req.add_header('Content-Type', 'application/json')
        jsondata = json.dumps(data).encode('utf-8')
        req.data = jsondata
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason}")
        return None
    except Exception as e:
        print(f"Connection Error: {e}")
        return None

def check_api_running():
    res = make_request(f"{API_URL}/")
    return res is not None

def run_benchmark():
    print("==================================================")
    print("GeoShardDB Redis Caching Benchmark")
    print("==================================================")
    
    # 1. Flush cache first
    print("Flushing cache...")
    make_request(f"{API_URL}/cache", method="DELETE")
        
    # Get a list of recent users to query
    print("Fetching recent users for benchmark targets...")
    res = make_request(f"{API_URL}/users/recent/all")
    if not res:
        print("Error: Could not retrieve users. Please ensure FastAPI is running.")
        sys.exit(1)
        
    recent_users = res.get("results", [])
    if not recent_users:
        print("No users found in database. Did you run seed_data.py?")
        sys.exit(1)
        
    targets = [u for u in recent_users if "user_id" in u][:5]
    print(f"Benchmark targets: {[(t['user_id'], t['region']) for t in targets]}")
    print("--------------------------------------------------")
    
    # Measure Cold Reads (Cache Misses -> Postgres DB)
    print("Running COLD READS (Database query)...")
    cold_times = []
    for target in targets:
        uid = target["user_id"]
        reg = target["region"]
        
        start = time.time()
        res = make_request(f"{API_URL}/users/{uid}?region={reg}")
        end = time.time()
        
        latency = (end - start) * 1000
        cold_times.append(latency)
        served_from = res.get("served_from_cache", False) if res else False
        print(f"User {uid} ({reg}): Latency = {latency:.2f} ms | Served from cache: {served_from}")
        
    avg_cold = sum(cold_times) / len(cold_times)
    print(f"Average Cold Read Latency: {avg_cold:.2f} ms")
    print("--------------------------------------------------")
    
    # Measure Warm Reads (Cache Hits -> Redis Cache)
    print("Running WARM READS (Redis cache query)...")
    warm_times = []
    for target in targets:
        uid = target["user_id"]
        reg = target["region"]
        
        start = time.time()
        res = make_request(f"{API_URL}/users/{uid}?region={reg}")
        end = time.time()
        
        latency = (end - start) * 1000
        warm_times.append(latency)
        served_from = res.get("served_from_cache", False) if res else False
        print(f"User {uid} ({reg}): Latency = {latency:.2f} ms | Served from cache: {served_from}")
        
    avg_warm = sum(warm_times) / len(warm_times)
    print(f"Average Warm Read Latency: {avg_warm:.2f} ms")
    print("--------------------------------------------------")
    
    # Print Stats
    speedup = avg_cold / avg_warm if avg_warm > 0 else 0
    print("BENCHMARK SUMMARY:")
    print(f"Average Cold Read: {avg_cold:.2f} ms")
    print(f"Average Warm Read: {avg_warm:.2f} ms")
    print(f"Cache Speedup Factor: {speedup:.2f}x")
    
    # Fetch Cache Stats
    stats_res = make_request(f"{API_URL}/cache/stats")
    if stats_res:
        print("\nRedis Cache Stats:")
        print(f"  - Hits: {stats_res['stats']['hits']}")
        print(f"  - Misses: {stats_res['stats']['misses']}")
        print(f"  - Hit Rate: {stats_res['stats']['hit_rate_pct']}%")
        print(f"  - Redis Memory: {stats_res['used_memory']}")
    print("==================================================")

if __name__ == "__main__":
    if not check_api_running():
        print("Error: GeoShardDB API server is not running on http://localhost:8000")
        print("Please start the server first.")
        sys.exit(1)
    run_benchmark()
