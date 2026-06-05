# os_concepts/page_replacement.py
# Cache eviction simulator using classic OS page replacement algorithms: FIFO, LRU, LFU, Clock, and Optimal.

from collections import OrderedDict, defaultdict

class CacheSimulator:
    def __init__(self, capacity):
        self.capacity = capacity

    def simulate_fifo(self, reference_string):
        """First-In, First-Out (FIFO) eviction"""
        cache = []
        faults = 0
        hits = 0
        evictions = []
        history = []

        for item in reference_string:
            if item in cache:
                hits += 1
                status = "HIT"
            else:
                faults += 1
                status = "MISS"
                evicted = None
                if len(cache) >= self.capacity:
                    evicted = cache.pop(0)
                    evictions.append(evicted)
                cache.append(item)
                
            history.append({
                "item": item,
                "status": status,
                "cache": list(cache),
                "evicted": evicted if status == "MISS" and len(cache) > self.capacity else None
            })

        return {
            "algorithm": "FIFO",
            "hits": hits,
            "faults": faults,
            "hit_rate_pct": round((hits / len(reference_string) * 100), 2) if reference_string else 0,
            "evictions_count": len(evictions),
            "history": history
        }

    def simulate_lru(self, reference_string):
        """Least Recently Used (LRU) eviction"""
        cache = OrderedDict()
        faults = 0
        hits = 0
        evictions = []
        history = []

        for item in reference_string:
            evicted = None
            if item in cache:
                hits += 1
                status = "HIT"
                # Move to end to mark as recently used
                cache.move_to_end(item)
            else:
                faults += 1
                status = "MISS"
                if len(cache) >= self.capacity:
                    # Pop first item (least recently used)
                    evicted_key, _ = cache.popitem(last=False)
                    evictions.append(evicted_key)
                    evicted = evicted_key
                cache[item] = True

            history.append({
                "item": item,
                "status": status,
                "cache": list(cache.keys()),
                "evicted": evicted
            })

        return {
            "algorithm": "LRU",
            "hits": hits,
            "faults": faults,
            "hit_rate_pct": round((hits / len(reference_string) * 100), 2) if reference_string else 0,
            "evictions_count": len(evictions),
            "history": history
        }

    def simulate_lfu(self, reference_string):
        """Least Frequently Used (LFU) eviction"""
        cache = set()
        counts = defaultdict(int)
        faults = 0
        hits = 0
        evictions = []
        history = []

        for item in reference_string:
            evicted = None
            counts[item] += 1
            
            if item in cache:
                hits += 1
                status = "HIT"
            else:
                faults += 1
                status = "MISS"
                if len(cache) >= self.capacity:
                    # Find item with lowest frequency count
                    lfu_item = min(cache, key=lambda x: (counts[x], reference_string.index(x) if x in reference_string else 0))
                    cache.remove(lfu_item)
                    evictions.append(lfu_item)
                    evicted = lfu_item
                cache.add(item)

            history.append({
                "item": item,
                "status": status,
                "cache": list(cache),
                "evicted": evicted
            })

        return {
            "algorithm": "LFU",
            "hits": hits,
            "faults": faults,
            "hit_rate_pct": round((hits / len(reference_string) * 100), 2) if reference_string else 0,
            "evictions_count": len(evictions),
            "history": history
        }

    def simulate_clock(self, reference_string):
        """Clock (Second Chance) eviction"""
        cache = [None] * self.capacity
        ref_bits = [0] * self.capacity
        pointer = 0
        faults = 0
        hits = 0
        evictions = []
        history = []

        for item in reference_string:
            evicted = None
            # Check if item is in cache
            if item in cache:
                hits += 1
                status = "HIT"
                idx = cache.index(item)
                ref_bits[idx] = 1 # Set reference bit to 1
            else:
                faults += 1
                status = "MISS"
                # Find page to replace using clock hand
                while True:
                    if cache[pointer] is None:
                        # Empty slot
                        cache[pointer] = item
                        ref_bits[pointer] = 1
                        pointer = (pointer + 1) % self.capacity
                        break
                    elif ref_bits[pointer] == 1:
                        # Second chance
                        ref_bits[pointer] = 0
                        pointer = (pointer + 1) % self.capacity
                    else:
                        # Evict
                        evicted = cache[pointer]
                        evictions.append(evicted)
                        cache[pointer] = item
                        ref_bits[pointer] = 1
                        pointer = (pointer + 1) % self.capacity
                        break

            history.append({
                "item": item,
                "status": status,
                "cache": [x for x in cache if x is not None],
                "evicted": evicted
            })

        return {
            "algorithm": "Clock",
            "hits": hits,
            "faults": faults,
            "hit_rate_pct": round((hits / len(reference_string) * 100), 2) if reference_string else 0,
            "evictions_count": len(evictions),
            "history": history
        }

    def simulate_optimal(self, reference_string):
        """Optimal (Bélády's) eviction - evict item used furthest in the future"""
        cache = set()
        faults = 0
        hits = 0
        evictions = []
        history = []

        for idx, item in enumerate(reference_string):
            evicted = None
            if item in cache:
                hits += 1
                status = "HIT"
            else:
                faults += 1
                status = "MISS"
                if len(cache) >= self.capacity:
                    # Find which cached item is used furthest in the future
                    farthest_idx = -1
                    farthest_item = None
                    
                    for cached_item in cache:
                        try:
                            # Search in future references
                            future_idx = reference_string.index(cached_item, idx + 1)
                        except ValueError:
                            # Not used in the future at all
                            future_idx = float('inf')
                            
                        if future_idx > farthest_idx:
                            farthest_idx = future_idx
                            farthest_item = cached_item
                            
                    cache.remove(farthest_item)
                    evictions.append(farthest_item)
                    evicted = farthest_item
                cache.add(item)

            history.append({
                "item": item,
                "status": status,
                "cache": list(cache),
                "evicted": evicted
            })

        return {
            "algorithm": "Optimal",
            "hits": hits,
            "faults": faults,
            "hit_rate_pct": round((hits / len(reference_string) * 100), 2) if reference_string else 0,
            "evictions_count": len(evictions),
            "history": history
        }
