import json
import time
import aiohttp
import asyncio
import ijson
import urllib
import sys

courses = {}
indexes = {}
SOC_URL = "http://sis.rutgers.edu/soc"
SOC_API_URL = SOC_URL + "/api"

snipes = []
with open("snipes.txt", "r") as f:
    for line in f:
        line = line.strip()
        if line:
            snipes.append(line)

if len(sys.argv) != 2:
    sys.exit(1)

ntfy_topic = sys.argv[1]

async def main():
    async with aiohttp.ClientSession() as s:
        td = await get_term_date(s)
        await update_courses(s, td)
        await asyncio.gather(
            course_loop(s, td),
            update_opened(s, td),
        )

async def get_term_date(s):
    r = await s.get(SOC_URL)
    PREFIX = b'<div id="initJsonData" style="display:none;">'
    soc_text = None
    async for line in r.content:
        if not line.startswith(PREFIX):
            continue
        soc_text = line.rstrip()[len(PREFIX):-len("</div>")]
        break
    term_date = json.loads(soc_text.decode(r.charset))["currentTermDate"]
    return term_date

async def update_courses(s, td):
    r = await s.get(f"{SOC_API_URL}/courses.json?year={td['year']}&term={td['term']}&campus={td['campus']}")
    async for course in ijson.items(r.content, 'item'):
        courses[course["courseString"]] = {
            "title": course["title"],
            "sections": dict([(sec["index"], sec["number"]) for sec in course["sections"]]),
        }
        for sec in course["sections"]:
            indexes[sec["index"]] = course["courseString"]

async def course_loop(s, td):
    ticker = tick(60 * 15)
    while True:
        await anext(ticker)
        await update_courses(s, td)

open_sections = None
async def update_opened(s, td):
    global open_sections
    ticker = tick(1)
    while True:
        await anext(ticker)
        params = {'year': td['year'], 'term': td['term'], 'campus': td['campus']}
        r = await s.get(f"{SOC_API_URL}/openSections.json", params=params)
        j = await r.json()
        if open_sections == None:
            open_sections = j
            continue
        just_opened = (s for s in j if s not in open_sections)
        open_sections = j
        for index in just_opened:
            if index not in snipes and indexes[index] not in snipes:
                continue
            params = {
                'login': 'cas',
                'semesterSelection': str(td['term'])+str(td['year']),
                'indexList': index,
            }
            click = "http://sims.rutgers.edu/webreg/editSchedule.htm?" + urllib.parse.urlencode(params)
            headers = {
                "Click": click
            }
            course = courses[indexes[index]]
            title = course["title"]
            section_n = course["sections"][index]
            msg = f"{title} section {section_n} ({index}) just opened!"
            await s.post("https://ntfy.sh/" + ntfy_topic, data=msg, headers=headers)

async def tick(interval):
    while True:
        yield 1
        await asyncio.sleep(interval)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
