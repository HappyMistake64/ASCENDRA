import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
class DashboardHandler(BaseHTTPRequestHandler):
    store=None
    def do_GET(self):
        if self.path=='/api/runs':
            data=json.dumps(self.store.latest()).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data);return
        html='''<!doctype html><meta charset="utf-8"><title>ASCENDRA</title><style>body{font-family:system-ui;background:#0b1020;color:#e8ecff;max-width:1000px;margin:40px auto;padding:20px}h1{color:#9ef}pre{background:#121a31;padding:16px;border-radius:12px;overflow:auto}.tag{color:#8f8}</style><h1>ASCENDRA Evidence Console</h1><p class=tag>CHANGE != IMPROVEMENT</p><p>Read-only local evidence view.</p><pre id=o>Loading...</pre><script>fetch('/api/runs').then(r=>r.json()).then(x=>o.textContent=JSON.stringify(x,null,2))</script>'''.encode()
        self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(html)
    def log_message(self,*a):pass
def serve(store,host='127.0.0.1',port=8769):
    DashboardHandler.store=store;print(f'ASCENDRA dashboard: http://{host}:{port}');ThreadingHTTPServer((host,port),DashboardHandler).serve_forever()
