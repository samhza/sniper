import json
import time
import aiohttp
import asyncio
import ijson
import urllib
import sys
from datetime import datetime

courses = {}
indexes = {}
open_times = {}
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
    async with s.get(SOC_URL) as r:
        PREFIX = b'<div id="initJsonData" style="display:none;">'
        soc_text = None
        async for line in r.content:
            if not line.startswith(PREFIX):
                continue
            soc_text = line.rstrip()[len(PREFIX):-len("</div>")]
            break
        term_date = json.loads(soc_text.decode(r.charset))["currentTermDate"]
        # hardcode for now...
        term_date = {
            "campus": "NB",
            "term": "9",
            "year": '2023',
        }
        return term_date

async def update_courses(s, td):
    params = {
        'year': td['year'],
        'term': td['term'],
        'campus': td['campus']
    }
    async with s.get(f"{SOC_API_URL}/courses.json", params=params) as r:
        async for course in ijson.items(r.content, 'item'):
            courses[course["courseString"]] = {
                "title": course["title"],
                "sections": {sec["index"]:sec["number"] for sec in course["sections"]},
            }
            for sec in course["sections"]:
                indexes[sec["index"]] = course["courseString"]
    print("ℹ️ Refreshed course listings!")
    return

async def course_loop(s, td):
    ticker = tick(60 * 15)
    await anext(ticker)
    while True:
        await anext(ticker)
        await update_courses(s, td)

def fmt_section(index):
    course = courses[indexes[index]]
    title = course["title"]
    section_n = course["sections"][index]
    return f"{title} section {section_n} ({index})"

open_sections = None
async def update_opened(s, td):
    global open_sections
    ticker = tick(1)
    while True:
        await anext(ticker)
        params = {
            'year': td['year'],
            'term': td['term'],
            'campus': td['campus']
        }
        r = await s.get(f"{SOC_API_URL}/openSections.json", params=params)
        j = await r.json()
        if open_sections == None:
            open_sections = j
            continue
        just_opened = [s for s in j if s not in open_sections]
        just_closed = [s for s in open_sections if s not in j]
        for index in just_closed:
            if index not in indexes:
                continue
            time_info = ""
            try:
                open_time = open_times[index]
                time_info = f" AFTER BEING OPEN FOR {(datetime.now() - open_time)}"
            except KeyError:
                pass
            print(f"❌ {fmt_section(index)} CLOSED{time_info}")
        open_sections = j
        for index in just_opened:
            if index not in indexes:
                continue
            open_times[index] = datetime.now()
            print(f"✅ {fmt_section(index)} OPENED")
            if index not in snipes and indexes[index] not in snipes:
                continue
            params = {
                'login': 'cas',
                'semesterSelection': f"{td['term']}{td['year']}",
                'indexList': index,
            }
            click = "http://sims.rutgers.edu/webreg/editSchedule.htm?" + urllib.parse.urlencode(params)
            headers = {
                "Click": click
            }
            msg = f"{fmt_section(index)} just opened!"
            async with s.post("https://ntfy.sh/" + ntfy_topic, data=msg, headers=headers):
                pass

async def tick(interval):
    while True:
        yield 1
        await asyncio.sleep(interval)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
