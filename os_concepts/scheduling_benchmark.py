# os_concepts/scheduling_benchmark.py
# Benchmark comparing different request scheduling algorithms

from scheduler import RequestScheduler, Request, generate_random_workload
import copy

def run_benchmark():
    print("==================================================")
    print("Request Scheduling Algorithm Benchmark")
    print("==================================================")
    
    # Generate a fixed workload of requests to evaluate all algorithms fairly
    original_workload = generate_random_workload(count=15)
    
    # Print workload details
    print("Workload Requests:")
    for r in original_workload:
        print(f"  {r.request_id}: Arrival={r.arrival_time}, Cost={r.cost_units}, Priority={r.priority}")
    print("--------------------------------------------------")

    scheduler = RequestScheduler()
    algorithms = ["FCFS", "SJF", "Priority", "Round Robin", "MLFQ"]
    
    results = {}
    
    # 1. FCFS
    workload = copy.deepcopy(original_workload)
    reqs, _ = scheduler.schedule_fcfs(workload)
    results["FCFS"] = reqs
    
    # 2. SJF
    workload = copy.deepcopy(original_workload)
    reqs, _ = scheduler.schedule_sjf(workload)
    results["SJF"] = reqs
    
    # 3. Priority
    workload = copy.deepcopy(original_workload)
    reqs, _ = scheduler.schedule_priority(workload)
    results["Priority"] = reqs
    
    # 4. RR
    workload = copy.deepcopy(original_workload)
    reqs, _ = scheduler.schedule_rr(workload, quantum=4)
    results["Round Robin"] = reqs
    
    # 5. MLFQ
    workload = copy.deepcopy(original_workload)
    reqs, _ = scheduler.schedule_mlfq(workload)
    results["MLFQ"] = reqs

    # Print Comparison Table
    print(f"{'Algorithm':<15} | {'Avg Wait Time':<15} | {'Avg Turnaround':<15}")
    print("-" * 52)
    for alg in algorithms:
        reqs = results[alg]
        avg_wait = sum(r.waiting_time for r in reqs) / len(reqs)
        avg_turnaround = sum(r.turnaround_time for r in reqs) / len(reqs)
        print(f"{alg:<15} | {avg_wait:<15.2f} | {avg_turnaround:<15.2f}")
    print("==================================================")

if __name__ == "__main__":
    run_benchmark()
