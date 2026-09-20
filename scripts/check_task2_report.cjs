// Visual QA for the self-contained report, not a production web dependency.
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const directory = path.resolve(process.argv[2] || 'outputs/task2_v11');
  const reportFile = process.argv[3] ? path.resolve(process.argv[3]) : path.join(directory, '任务二进度总览.html');
  fs.mkdirSync(directory, {recursive: true});
  const browser = await chromium.launch({headless: true, channel: process.env.BROWSER_CHANNEL || undefined});
  const results = [];
  for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
    const page = await browser.newPage({viewport: {width, height}, deviceScaleFactor: 1});
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto(pathToFileURL(reportFile).href);
    await page.screenshot({path: path.join(directory, `report_${name}.png`), fullPage: false});
    const measurements = await page.evaluate(() => ({
      documentWidth: document.documentElement.scrollWidth,
      viewport: window.innerWidth,
      tables: document.querySelectorAll('table').length,
      headings: [...document.querySelectorAll('h1,h2')].map(e => e.textContent),
      badTextBoxes: [...document.querySelectorAll('p,h1,h2,.metrics div,.flow div')]
        .filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.textContent.slice(0, 80))
    }));
    results.push({name, ...measurements, errors});
    if (errors.length || measurements.documentWidth > width + 1 || measurements.badTextBoxes.length) {
      process.exitCode = 1;
    }
    await page.close();
  }
  await browser.close();
  fs.writeFileSync(path.join(directory, 'visual_qa.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
})().catch(e => { console.error(e); process.exitCode = 1; });
