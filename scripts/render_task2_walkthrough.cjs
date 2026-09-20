// Render the explanatory document without altering experiment records.
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
(async () => {
  const marked = await import(process.env.MARKED_MODULE ? pathToFileURL(process.env.MARKED_MODULE).href : 'marked');
  const root = path.resolve(__dirname, '..');
  const source = path.join(root, 'docs', '任务二Demo案例与实现讲解.md');
  let content = marked.marked.parse(fs.readFileSync(source, 'utf8'));
  const toc = [];
  let index = 0;
  content = content.replace(/<h2>(.*?)<\/h2>/g, (_, title) => {
    const id = 'section-' + (++index);
    toc.push(`<a href="#${id}">${title}</a>`);
    return `<h2 id="${id}">${title}</h2>`;
  }).replace(/<table>/g, '<div class="table-scroll"><table>').replace(/<\/table>/g, '</table></div>');
  const css = `*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:#252b30;background:white;font:16px/1.9 'Microsoft YaHei',sans-serif;letter-spacing:0}main{max-width:1000px;margin:auto;padding:36px 32px 72px}h1{font-size:27px;line-height:1.5}h2{font-size:23px;margin-top:52px;padding-top:18px;border-top:2px solid #28786e;scroll-margin-top:12px}h3{font-size:18px;margin-top:30px}p,li{overflow-wrap:anywhere}a{color:#176a80;text-decoration-thickness:1px}nav{padding:16px 0;border-bottom:1px solid #cfd8db;display:grid;gap:6px}nav a{font-size:14px}code{font:14px/1.6 Consolas,'Microsoft YaHei',monospace;background:#f0f3f4;padding:2px 4px;overflow-wrap:anywhere}pre{background:#f4f7f8;border-left:3px solid #28786e;padding:16px 18px;overflow:auto}pre code{background:none;padding:0;white-space:pre;overflow-wrap:normal}table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.7}th,td{text-align:left;vertical-align:top;border:1px solid #d7dfe2;padding:10px 12px;min-width:90px}th{background:#edf4f2}tr:nth-child(even){background:#fafbfc}.table-scroll{overflow-x:auto}header{font-size:13px;color:#606970}strong{color:#1a504b}@media(max-width:650px){main{padding:18px 16px 48px}h1{font-size:23px}h2{font-size:21px}body{font-size:15px}pre{padding:12px}}@media print{nav{display:none}main{padding:0}h2,h3{break-after:avoid}pre{white-space:pre-wrap}pre code{white-space:pre-wrap}tr{break-inside:avoid}}`;
  const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>任务二Demo：案例与实现讲解</title><style>${css}</style><main><header>案例讲解版 · 对应v1.1真实记录 · 未更改历史成绩</header><nav aria-label="章节目录">${toc.join('')}</nav>${content}</main></html>`;
  const out = path.join(root, 'docs', '任务二Demo案例与实现讲解.html');
  fs.writeFileSync(out, html);
  console.log(out);
})().catch(e => { console.error(e); process.exitCode = 1; });
