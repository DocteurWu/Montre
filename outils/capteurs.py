"""Accéléromètre en direct : la montre te dit quoi faire, le PC affiche x, y, z.

Usage : python capteurs.py [secondes]
La montre passe en mode test usine pendant la mesure, puis redémarre à la fin.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # accès à ido.py
import asyncio
import sys
import time

from ido import Watch


async def main():
    duree = float(sys.argv[1]) if len(sys.argv) > 1 else 20
    async with Watch() as w:
        await w.message("Capteurs", "Pose la montre a plat, ne bouge plus")
        await asyncio.sleep(4)
        await w.test_mode(True)
        t0 = time.time()
        try:
            while time.time() - t0 < duree:
                xyz = await w.accel()
                t = time.time() - t0
                if xyz:
                    x, y, z = xyz
                    mag = (x * x + y * y + z * z) ** 0.5
                    print(f"{t:5.1f}s  x={x:6d}  y={y:6d}  z={z:6d}  |a|={mag:7.1f}  " + "#" * int(mag / 8))
                await asyncio.sleep(0.2)
        finally:
            try:
                await w.test_mode(False)
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
