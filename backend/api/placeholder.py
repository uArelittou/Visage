"""前端还没构建（frontend/dist 不存在）时显示的占位页。"""

PLACEHOLDER_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>千面录</title>
<style>
  body { font: 15px/1.7 "Microsoft YaHei", sans-serif; margin: 12vh auto; max-width: 520px; padding: 0 24px; color: #2b2b2b; }
  h1 { font-weight: 500; letter-spacing: .2em; margin-bottom: .2em; }
  .muted { color: #888; }
  code { background: #f2f2f2; padding: 1px 6px; border-radius: 3px; }
</style>
</head>
<body>
<h1>千面录</h1>
<p>后端已就绪</p>
<p id="info" class="muted">正在读取卡库…</p>
<script>
fetch("/api/library").then(r => r.json()).then(d => {
  const el = document.getElementById("info");
  if (d.open && d.source_count) el.textContent = "共 " + d.card_count + " 张卡，来源 " + d.source_count + " 个";
  else if (d.opening) el.textContent = "正在打开卡库…";
  else el.innerHTML = "尚未添加来源。可调用 <code>POST /api/sources</code> 添加文件夹或单张卡。";
}).catch(() => { document.getElementById("info").textContent = "读取失败"; });
</script>
</body>
</html>
"""
