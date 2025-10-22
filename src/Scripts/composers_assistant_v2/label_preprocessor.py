import collections
import os
import json

LABEL_MAP = {
    "Intro": "Intro",
    "Outro": "Outro",
    "Verse": "Verse",
    "Pre-Chorus": "Pre-Chorus",
    "Chorus": "Chorus",
    "Bridge": "Bridge",
    "Solo": "Solo",

    "Pre-Verse": "Instrumental",
    "Post-Chorus": "Instrumental",
    "Instrumental": "Instrumental",
    "Interlude": "Instrumental",
    "Transition": "Instrumental",

    "Coda": "Outro",
    "End": "End",

    "Other": "Other"
}


def _process_pre_verses_in_intro(L: list[tuple[int, float, str]]) -> list[tuple[int, float, str]]:
    res = []
    in_intro = True
    for i, t, label in L:
        if label != 'Intro' and label != 'Pre-Verse':
            in_intro = False
        if in_intro and label == 'Pre-Verse':
            label = 'Intro'
        res.append((i, t, label))
    return res


def _process_remove_consecutive_identical_labels(L: list[tuple[int, float, str]]) -> list[tuple[int, float, str]]:
    res = []
    cur_label = ''
    for i, t, label in L:
        if label != cur_label:
            res.append((i, t, label))
        cur_label = label
    return res


def _process_bridge_to_chorus(L: list[tuple[int, float, str]]) -> list[tuple[int, float, str]]:
    res = []
    counter = collections.Counter()
    for i, t, label in L:
        counter[label] += 1
    if counter['Verse'] >= 1 and counter['Bridge'] >= 2 and counter['Pre-Chorus'] == 0 and counter['Chorus'] == 0 and \
            counter['Post-Chorus'] == 0:
        for i, t, label in L:
            if label == 'Bridge':
                label = 'Chorus'
            res.append((i, t, label))
    else:
        res = L
    return res


# def has_overlapping_labels(L: list[list[float | str]], threshold: float = 0.01):
def has_overlapping_labels(L: list, threshold: float = 0.01):
    seen = set()
    for tup in L:
        t, label = tup
        if any(abs(t-x) < threshold for x in seen):
            return True
        seen.add(t)
    return False


# def preprocess_labels(L: list[list[float | str]], remove_consecutive_identical=False) -> list[list[float | str]]:
def preprocess_labels(L: list, remove_consecutive_identical=False) -> list:
    # discard Fadeouts. Don't apply the simplifying label map yet
    working_labels = []
    for i, tup in enumerate(L):
        t, label = tup
        t: float
        label: str
        label = label.split(';')[0].split(' + ')[0]
        if label != 'Fadeout':
            working_labels.append((i, t, label))

    # Change pre-verse to intro if intro is the only label seen so far (reading left to right).
    # (This is why we don't apply the simplifying label map yet.)
    working_labels = _process_pre_verses_in_intro(working_labels)

    # Apply label simplifying map.
    working_labels = [(i, t, LABEL_MAP[label]) for (i, t, label) in working_labels]

    # change bridge to chorus in songs that:
    # have >= 1 verse AND
    # have >= 2 bridges AND
    # have no pre-chorus, no chorus, and no post-chorus
    working_labels = _process_bridge_to_chorus(working_labels)

    if remove_consecutive_identical:
        working_labels = _process_remove_consecutive_identical_labels(working_labels)

    final_labels = []
    for tup in working_labels:
        i, t, label = tup
        final_labels.append([t, label])

    return final_labels
