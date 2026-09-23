import json
import sys

import gen_ltx as G


def main():
    picks = [tuple(int(x) for x in p.split(":")) for p in sys.argv[1:]] or [(1, 0), (3, 2)]
    length = int(sys.argv[-1]) if len(sys.argv) > 2 and sys.argv[-1].isdigit() else 33
    if length == int(sys.argv[-1]):
        picks = [tuple(int(x) for x in p.split(":")) for p in sys.argv[1:-1]] or [(1, 0), (3, 2)]

    plan = json.load(open(G.PLANB / "shots.json", encoding="utf-8"))
    shots = []
    for sh in plan["shots"]:
        segs = sh.get("segments") or []
        chosen = [dict(s, seg_index=i) for i, s in enumerate(segs) if (sh["id"], i) in picks]
        if chosen:
            s2 = dict(sh)
            s2["segments"] = chosen
            shots.append(s2)
    G.plan = {"title": plan.get("title", "test"), "shots": shots}
    G.LENGTH = length
    G.run_vids()


if __name__ == "__main__":
    main()
