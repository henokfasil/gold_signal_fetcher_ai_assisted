#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import CDP from '/opt/tradingview-mcp/node_modules/chrome-remote-interface/index.js';

const dirs = fs.readdirSync('/tmp')
  .filter(name => name.includes('-tradingview-session.service-'))
  .map(name => path.join('/tmp', name, 'tmp', 'tradingview_auth_url'))
  .filter(file => fs.existsSync(file));

if (!dirs.length) throw new Error('No captured TradingView authorization URL');
const authFile = dirs.sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs)[0];
const authUrl = fs.readFileSync(authFile, 'utf8');
const parsed = new URL(authUrl);
if (parsed.protocol !== 'https:' || parsed.hostname !== 'auth.tradingview.com') {
  throw new Error('Captured URL is not an official TradingView authorization URL');
}

const targets = await CDP.List({host: '127.0.0.1', port: 9222});
const target = targets.find(item => item.type === 'page' && item.url.includes('tradingview.com/chart'));
if (!target) throw new Error('No TradingView chart target found');

const client = await CDP({host: '127.0.0.1', port: 9222, target});
try {
  await client.Page.enable();
  await client.Page.navigate({url: authUrl});
  fs.unlinkSync(authFile);
  console.log('TradingView authorization page opened in the VPS session');
} finally {
  await client.close();
}
