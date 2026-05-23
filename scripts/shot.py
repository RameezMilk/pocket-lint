"""Screenshot the dashboard with a mocked event stream (no live API needed).

Replaces window.EventSource before the page's auto-run fires, replaying a
realistic sequence (using the real highlight coords) so we can verify the
white/minimal look, the typed agent cards, flags, and on-document highlights.
"""
import asyncio
from playwright.async_api import async_playwright

MOCK = r"""
window.EventSource = class {
  constructor(url){
    this.url = url;
    const seq = [
      [200,  {kind:'agent_start', role:'auditor', agent:'pocket-lint-structural-auditor'}],
      [250,  {kind:'agent_start', role:'checker', agent:'pocket-lint-consistency-checker'}],
      [300,  {kind:'script', role:'auditor', code:'import PyPDF2\ntoc = PyPDF2.PdfReader("/workspace/synthetic_csr.pdf").pages[0].extract_text().lower()\nmandatory = {1:"Title Page", ..., 12:"Safety Evaluation", ...}\nmissing = [f"{n} {t}" for n,t in mandatory.items() if t.lower() not in toc]\nprint("missing:", missing)'}],
      [320,  {kind:'script', role:'checker', code:'import PyPDF2, pandas as pd, re\nr = PyPDF2.PdfReader("/workspace/synthetic_csr.pdf")\nnarrative_total = int(re.search(r"total of (\\d+) patients", r.pages[1].extract_text()).group(1))\nsites = ["Boston","Chicago","Houston","Seattle"]\nsite_counts = [int(re.search(s+r"\\D+(\\d+)", r.pages[2].extract_text()).group(1)) for s in sites]\ncomputed_total = int(pd.Series(site_counts).sum())\nprint(narrative_total, computed_total)'}],
      [500,  {kind:'step', role:'auditor', step_type:'function_call'}],
      [560,  {kind:'step', role:'checker', step_type:'function_call'}],
      [900,  {kind:'code', role:'auditor', code:'x'}],
      [980,  {kind:'code', role:'checker', code:'x'}],
      [1600, {kind:'findings', role:'checker', findings:[{check:'consistency', status:'fail', severity:'high', page:2, anchor_text:'250', secondary_page:3, secondary_anchor_text:'247', message:'The narrative states 250 patients enrolled, but Table 14.1 sums to 247.', evidence:'62+58+49+78 = 247', boxes:[{x:241,y:462,w:51,h:35,page:2},{x:886,y:558,w:51,h:35,page:3}]}]}],
      [1700, {kind:'agent_done', role:'checker'}],
      [2400, {kind:'findings', role:'auditor', findings:[{check:'structural', status:'fail', severity:'high', page:1, anchor_text:'13 Discussion and Overall Conclusions', message:'Section 12 Safety Evaluation is missing from the table of contents.', evidence:'§11 Efficacy is followed directly by §13 Discussion', boxes:[{x:174,y:885,w:453,h:35,page:1}]}]}],
      [2500, {kind:'agent_done', role:'auditor'}],
      [2700, {kind:'done'}],
    ];
    setTimeout(()=>{ for(const [t,d] of seq) setTimeout(()=>this.onmessage && this.onmessage({data:JSON.stringify(d)}), t); }, 10);
  }
  close(){}
};
"""

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1440, "height": 900},
                              device_scale_factor=2)
        await pg.add_init_script(MOCK)          # install mock BEFORE page scripts run
        await pg.goto("http://127.0.0.1:8000/", wait_until="networkidle")
        await pg.wait_for_timeout(6000)         # let typewriter + events finish
        await pg.screenshot(path="data/_ui.png", full_page=False)
        print("wrote data/_ui.png")
        await b.close()

asyncio.run(main())
