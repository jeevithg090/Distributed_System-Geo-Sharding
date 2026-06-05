# os_concepts/memory_benchmark.py
# Benchmark comparing cache page replacement (eviction) algorithms

from page_replacement import CacheSimulator

def run_benchmark():
    print("==================================================")
    print("Cache Eviction / Page Replacement Benchmark")
    print("==================================================")
    
    # Access trace simulating realistic caching hits/misses
    trace = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5, 6, 1, 2, 3, 7, 8, 9, 1, 2, 3]
    capacity = 4
    
    print(f"Trace size: {len(trace)} accesses")
    print(f"Cache capacity: {capacity} items")
    print(f"Trace: {trace}")
    print("--------------------------------------------------")
    
    sim = CacheSimulator(capacity)
    algorithms = ["FIFO", "LRU", "LFU", "Clock", "Optimal"]
    results = {}
    
    results["FIFO"] = sim.simulate_fifo(trace)
    results["LRU"] = sim.simulate_lru(trace)
    results["LFU"] = sim.simulate_lfu(trace)
    results["Clock"] = sim.simulate_clock(trace)
    results["Optimal"] = sim.simulate_optimal(trace)
    
    # Print comparison table
    print(f"{'Algorithm':<12} | {'Hits':<8} | {'Faults':<8} | {'Hit Rate %':<12} | {'Evictions':<10}")
    print("-" * 57)
    for alg in algorithms:
        res = results[alg]
        print(f"{alg:<12} | {res['hits']:<8} | {res['faults']:<8} | {res['hit_rate_pct']:<12.2f} | {res['evictions_count']:<10}")
    print("==================================================")

if __name__ == "__main__":
    run_benchmark()
