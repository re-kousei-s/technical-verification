"""端末 F2-FC79 の線（管理画面で置いた 3 本）で、動画を数える。"""
import sys

sys.path.insert(0, "/t")
import evalcore as E  # noqa: E402

LINES = [{"id": "l1", "name": "線1", "line": [[0.4493, 0.7669], [0.2699, 0.9423]]},
         {"id": "l2", "name": "線2", "line": [[0.6055, 0.6113], [0.5007, 0.7176]]},
         {"id": "l3", "name": "線3", "line": [[0.7189, 0.5364], [0.6528, 0.6178]]}]

if __name__ == "__main__":
    for name in sys.argv[1:]:  # 例: PXL_20261030_032725923_960_512k.lite0
        for ms in (0.2, 0.25, 0.3):
            d, fr = E.load(f"/o/{name}.json", ms)
            ev, _ = E.run(d, fr, LINES, edge=0.3)
            print(f"{name} min_score={ms}", [(e[0], e[1], e[3]) for e in ev])
