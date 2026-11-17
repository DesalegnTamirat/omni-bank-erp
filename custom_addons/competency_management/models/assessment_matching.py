# -*- coding: utf-8 -*-
"""Choose assessment pairs while prioritizing coverage of each employee.

The inputs use employee ids for targets and user ids for assessors.  Existing
pairs are fixed: this helper only returns additional pairs for a cycle.
"""

from collections import Counter, defaultdict, deque


def allocate_balanced_assessments(candidate_map, limit, existing_pairs=()):
    """Give each target up to ``limit`` eligible raters, then balance workloads.

    A target with fewer than ``limit`` eligible raters receives all of them.
    Assessor workloads are best-effort because eligibility may force one user
    to assess many targets.  Existing pairs count toward both limits and loads,
    but are never reassigned or removed.
    """
    if limit <= 0:
        return []

    candidates = {
        target_id: tuple(sorted(set(assessor_ids)))
        for target_id, assessor_ids in candidate_map.items()
    }
    candidate_assessors = {user_id for users in candidates.values() for user_id in users}
    existing_by_target = defaultdict(set)
    workload = Counter()
    for target_id, assessor_id in set(existing_pairs):
        existing_by_target[target_id].add(assessor_id)
        workload[assessor_id] += 1

    assigned_by_target = {
        target_id: set(existing_by_target[target_id])
        for target_id in candidates
    }
    new_by_target = defaultdict(set)
    new_targets_by_assessor = defaultdict(set)

    # Constrained targets go first.  Never sacrifice an employee's rater quota
    # merely to keep an assessor at the preferred workload.
    for target_id in sorted(candidates, key=lambda target: (len(candidates[target]), target)):
        eligible = candidates[target_id]
        assigned = assigned_by_target[target_id]
        quota = min(limit, len(set(eligible) | assigned))
        needed = max(0, quota - len(assigned))
        available = (assessor_id for assessor_id in eligible if assessor_id not in assigned)
        for assessor_id in sorted(available, key=lambda user_id: (workload[user_id], user_id))[:needed]:
            assigned.add(assessor_id)
            new_by_target[target_id].add(assessor_id)
            new_targets_by_assessor[assessor_id].add(target_id)
            workload[assessor_id] += 1

    # A transfer path moves one assignment from a busy assessor to a less
    # busy one, possibly via other assessors.  Every intermediate target keeps
    # the same number of raters.  Only new assignments can be transferred.
    while True:
        if not candidate_assessors:
            break
        lightest_load = min(workload[user_id] for user_id in candidate_assessors)
        improving_path = None
        for start_id in sorted(new_targets_by_assessor, key=lambda user_id: (-workload[user_id], user_id)):
            if not new_targets_by_assessor[start_id] or workload[start_id] - lightest_load < 2:
                continue
            queue = deque([start_id])
            previous = {start_id: None}
            while queue and improving_path is None:
                current_id = queue.popleft()
                for target_id in sorted(new_targets_by_assessor[current_id]):
                    for alternative_id in candidates[target_id]:
                        if alternative_id in assigned_by_target[target_id] or alternative_id in previous:
                            continue
                        previous[alternative_id] = (current_id, target_id)
                        if workload[start_id] - workload[alternative_id] >= 2:
                            path = []
                            cursor = alternative_id
                            while previous[cursor] is not None:
                                prior_id, moved_target_id = previous[cursor]
                                path.append((prior_id, cursor, moved_target_id))
                                cursor = prior_id
                            improving_path = list(reversed(path))
                            break
                        queue.append(alternative_id)
                    if improving_path is not None:
                        break
            if improving_path is not None:
                break

        if improving_path is None:
            break

        for old_id, new_id, target_id in improving_path:
            assigned_by_target[target_id].remove(old_id)
            assigned_by_target[target_id].add(new_id)
            new_by_target[target_id].remove(old_id)
            new_by_target[target_id].add(new_id)
            new_targets_by_assessor[old_id].remove(target_id)
            new_targets_by_assessor[new_id].add(target_id)
            workload[old_id] -= 1
            workload[new_id] += 1

    return [
        (target_id, assessor_id)
        for target_id in sorted(new_by_target)
        for assessor_id in sorted(new_by_target[target_id])
    ]
