"""Read-only local CFD virtual-account dashboard. Run: python scripts/cfd_local_dashboard.py"""
from __future__ import annotations
import json
import html
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BRANCH = "gpt/autonomous-demo-runner"
URL = "https://raw.githubusercontent.com/sakagitnat/v1/" + BRANCH + "/state/cfd_bot_state.json"

def load_state():
    with urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "cfd-readonly-dashboard"}), timeout=20) as response:
        return json.load(response)

def report(state):
    accounts = state.get("virtual_accounts", {})
    positions = state.get("paper_positions", {})
    rows = []
    for key, account in sorted(accounts.items(), key=lambda item: (item[1].get("execution_tier", ""), item[0])):
        start = float(account.get("starting_equity") or 0)
        equity = float(account.get("equity", start))
        pnl = float(account.get("realized_pnl", equity - start))
        peak = float(account.get("high_water_mark") or max(start, equity))
        drawdown = (peak - equity) / peak * 100 if peak else 0
        opened = [p for p in positions.values() if p.get("virtual_account_id") == key]
        rows.append(dict(id=key, tier=account.get("execution_tier", "?"), strategy=account.get("strategy_tag") or "—",
                         tf=account.get("entry_timeframe") or "—", start=start, equity=equity, pnl=pnl,
                         closed=account.get("closed_trades", 0), wins=account.get("wins", 0),
                         losses=account.get("losses", 0), dd=drawdown, open=len(opened),
                         stop_risk=sum(float(p.get("risk_amount") or 0) for p in opened)))
    return rows

def render(rows):
    tiers = ["ACTIVE_DEMO", "PAPER", "SHADOW"]
    style = """body{font:15px system-ui;background:#101724;color:#e7edf6;margin:30px}
    h1{font-size:25px}p{color:#aab8ce}.cards{display:flex;gap:12px;flex-wrap:wrap}
    .card{padding:18px;background:#1d293a;border-radius:12px;min-width:180px}
    .card strong{font-size:23px}table{width:100%;border-collapse:collapse;margin:22px 0;font-size:13px}
    th,td{padding:9px;border-bottom:1px solid #344157;text-align:right}
    th:first-child,td:first-child{text-align:left}th{color:#aab8ce}
    .loss{color:#ff8e8e}.gain{color:#79d9ac}a{color:#92c6ff}
    .scroll{overflow-x:auto}"""
    parts = ['<!doctype html><html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CFD Research Dashboard</title><style>'+style+'</style><h1>CFD / Deriv — Research Dashboard</h1>',
             '<p>Read-only • Realized equity only • Unrealized P&L and gross gains/losses are not available in this state snapshot. Drawdown shown is current drawdown from recorded peak, NOT maximum historical drawdown. Refresh browser for latest committed state.</p>']
    for tier in tiers:
        group = [r for r in rows if r["tier"] == tier]
        start = sum(r["start"] for r in group)
        equity = sum(r["equity"] for r in group)
        pnl = sum(r["pnl"] for r in group)
        parts.append(f'<div class="card"><b>{tier}</b><p>{len(group)} accounts</p><strong>${equity:,.2f}</strong><p>Starting ${start:,.2f} • Realized P&L <span class="{"gain" if pnl>=0 else "loss"}">${pnl:+,.2f}</span></p></div>')
    parts.append('<h2>บัญชีทั้งหมด</h2><div class="scroll"><table><thead><tr><th>Account</th><th>Tier</th><th>Strategy</th><th>TF</th><th>Start</th><th>Equity</th><th>Realized</th><th>Closed</th><th>W/L</th><th>Current DD %</th><th>Open PAPER</th><th>Stop risk</th></tr></thead><tbody>')
    for r in rows:
        cells = [html.escape(str(r["id"])),html.escape(str(r["tier"])),html.escape(str(r["strategy"])),html.escape(str(r["tf"])),f'${r["start"]:.2f}',f'${r["equity"]:.2f}',f'${r["pnl"]:+.2f}',str(r["closed"]),f'{r["wins"]}/{r["losses"]}',f'{r["dd"]:.2f}',str(r["open"]),f'${r["stop_risk"]:.2f}']
        parts.append('<tr>'+''.join('<td'+(' class="loss"' if i==6 and r["pnl"]<0 else ' class="gain"' if i==6 and r["pnl"]>0 else '')+'>'+cell+'</td>' for i,cell in enumerate(cells))+'</tr>')
    parts.append('</tbody></table></div><p>Safety: this program performs HTTP GET only. It never sends orders, credentials, or repository writes.</p></html>')
    return ''.join(parts).encode("utf-8")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        try:
            data = render(report(load_state()))
            self.send_response(200)
        except Exception as exc:
            data = ("Unable to load GitHub state: " + html.escape(str(exc))).encode()
            self.send_response(503)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

if __name__ == "__main__":
    print("Open http://127.0.0.1:8765 — Ctrl+C to stop")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
