import subprocess
for u in ["https://data-sanpo.com/vendor/maplibre-gl@6.11.2/maplibre-gl.mjs",
          "https://data-sanpo.com/vendor/maplibre-gl%406.11.2/maplibre-gl.mjs",
          "https://data-sanpo.com/vendor/maplibre-gl@6.11.2/maplibre-gl-worker.mjs",
          "https://data-sanpo.com/vendor/maplibre-gl@6.11.2/maplibre-gl-shared.mjs",
          "https://data-sanpo.com/_astro/"]:
    print("==",u)
    print(subprocess.run(["curl","-sS","-o","/dev/null","-D","-","-H","Accept-Encoding: br, gzip",u],capture_output=True,text=True).stdout)
html=subprocess.run(["curl","-sS","https://data-sanpo.com/map/"],capture_output=True,text=True).stdout
import re
print(sorted(set(re.findall(r'(?:src|href)="(/[^"]+\.m?js[^"]*)"',html))))
print(re.findall(r'maplibre[^"\' ]{0,80}',html)[:10])
