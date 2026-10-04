import json, urllib.request, datetime as d
from collections import Counter
for job in ("kma_weather_alerts_job", "kma_ultra_short_nowcast_job"):
    q = {"query": '{ runsOrError(filter:{pipelineName:"%s"}, limit:14){ ... on Runs { results { status startTime } } } }' % job}
    req = urllib.request.Request("http://127.0.0.1:11002/graphql", json.dumps(q).encode(), {"content-type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=30))["data"]["runsOrError"]["results"]
    print("==", job, dict(Counter(x["status"] for x in r)))
    print("  ", " ".join(d.datetime.fromtimestamp(x["startTime"], d.UTC).strftime("%m-%d %H:%M") + "=" + x["status"][:4] for x in r if x["startTime"]))
