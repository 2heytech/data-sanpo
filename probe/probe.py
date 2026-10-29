import subprocess, re
html=subprocess.run(["curl","-sS","https://data-sanpo.com/map/"],capture_output=True,text=True).stdout
print("map html vendor:", sorted(set(re.findall(r'/vendor/[^"\']+',html))))
for f in ["maplibre-gl.mjs","maplibre-gl-shared.mjs","maplibre-gl-worker.mjs"]:
    u="https://data-sanpo.com/vendor/maplibre-gl-6.11.2/"+f
    h=subprocess.run(["curl","-sS","-o","/dev/null","-D","-","-H","Accept-Encoding: br, gzip",u],capture_output=True,text=True).stdout
    print("==",u); print("\n".join(l for l in h.splitlines() if re.match(r'(HTTP|location|cache-control|content-type|content-length)',l,re.I)))
