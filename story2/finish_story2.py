# -*- coding: utf-8 -*-
"""收养 ComfyUI 队列中遗留的 running 任务, 然后接 run_vids 续跑剩余段.

背景: gen_ltx 后台进程被系统回收, 但已提交的 shot01-02 仍在 ComfyUI 队列 running.
本脚本: 1) 动态取 queue_running 第一个任务, poll history 直到完成并 download 到 videos/
       2) 调 gen_ltx.run_vids() 续跑剩余段 (run_vids 已改无限重试, 崩了自动等重启)
"""
import gen_ltx as G
import time, json, re, os, urllib.request

COMFY = G.COMFY


def get_running_pids():
    try:
        d = json.loads(urllib.request.urlopen(COMFY + "/queue", timeout=30).read())
        return [r[1] for r in d.get("queue_running", [])]
    except Exception as e:
        print("get_running_pids err:", e)
        return []


def adopt_one(pid):
    print("adopting running pid:", pid)
    t0 = time.time()
    while time.time() - t0 < 3600:
        try:
            h = json.loads(urllib.request.urlopen(COMFY + "/history/" + pid, timeout=60).read())
            if pid in h:
                rec = h[pid]
                out = G.fetch_outputs(rec)
                if out:
                    fn = out[1]
                    m = re.search(r"shot_(\d+)_(\d+)", fn)
                    if m:
                        dest = os.path.join(G.OUT_VID, "shot_%s_%s.mp4" % (m.group(1), m.group(2)))
                        if os.path.exists(dest) and os.path.getsize(dest) > 10000:
                            print("already exists, skip:", dest)
                            return True
                        G.download(out, dest)
                        print("ADOPTED ->", dest, os.path.getsize(dest), "bytes")
                        return True
                    else:
                        print("cannot parse shot index from filename:", fn)
                        return False
                else:
                    print("  no output yet, waiting (pid=%s)" % pid[:8])
        except Exception as e:
            print("  poll err:", repr(e)[:120])
        time.sleep(8)
    print("adopt timeout for", pid)
    return False


if __name__ == "__main__":
    dest02 = os.path.join(G.OUT_VID, "shot_01_02.mp4")
    if os.path.exists(dest02) and os.path.getsize(dest02) > 10000:
        print("[adopt] shot_01_02 already present, skip adopt")
    else:
        pids = get_running_pids()
        if pids:
            print("[adopt] running pids:", pids)
            adopt_one(pids[0])
        else:
            print("[adopt] no running task; run_vids will regenerate shot01_02 if missing")
    print("=" * 50)
    print("[continue] running gen_ltx.run_vids() (resume remaining segments)")
    print("=" * 50)
    G.run_vids()
    print("=" * 50)
    print("ALL DONE: finish_story2 complete")
