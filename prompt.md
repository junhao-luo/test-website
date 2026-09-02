你是一名前端工程師。請產出**一個單一 HTML 檔案**（檔名 index.html），內容包含 <head><style> 與
<body><script>，做出一個「失物招領登錄系統」的前端頁面。請完全依照以下規格逐項實作，不要自由發揮、
不要「優化」或簡化任何一個規格。規格裡沒提到的地方才用你自己的判斷。

## 0. 產品目標與使用情境

這是一個給行政人員在撿到遺失物當下使用的登錄工具：對著撿到的物品拍一張照片，用一句自然語言補充
描述，選好拾獲地點與時間，按下送出後，前端會把「照片（base64）＋描述文字＋各種時間欄位」包成一包
JSON，POST 到一個 n8n 的 webhook；n8n 那端會用 LLM 辨識照片內容、抽取結構化資料、寫入 Google
Sheet，並把結構化結果回傳，前端要把回傳的 JSON 用一個 key/value 表格顯示出來。

## 1. 硬性技術約束（不可違反）

- **只能有一個 HTML 檔案**，CSS 寫在 `<head>` 的 `<style>` 裡，JS 寫在 `<body>` 底部的一個
  `<script>` 裡，全部包在一個 IIFE `(function(){ 'use strict'; ... })();` 裡。
- **零外部相依**：不可以引用任何 CDN、任何 npm 套件、任何外部字型檔（不可以用 Google Fonts 之類的
  `<link>`）、不可以用任何前端框架（React/Vue 都不行）。全部用原生 DOM API 與原生 JS（`var`
  宣告即可，不必用 ES6 class，本檔案風格是 function + var）。
- 這個網頁會用 `python3 -m http.server` 在樹莓派上直接跑起來，**必須用 `http://localhost` 開啟**
  （不能是區網 IP、不能是 `file://`）。原因：`navigator.mediaDevices.getUserMedia`（相機權限）只在
  secure context 下可用，瀏覽器把 `localhost` 視為 secure context 的特例，但區網 IP／`file://`
  不算。程式碼裡要针對「非 secure context 且非 localhost/127.0.0.1」的情況給出對應錯誤提示（見
  第 6 節相機錯誤訊息）。
- 介面文案一律使用**繁體中文**，`<html lang="zh-Hant">`。
- `<head>` 需包含 `<meta charset="UTF-8">` 與
  `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`，
  `<title>` 為「失物招領登錄」。

## 2. 整體 DOM 結構（由上到下）

1. `<header>`：sticky 頂欄。內容依序是：
   - `<h1>失物招領登錄</h1>`
   - 一個相機狀態徽章 `<span class="badge" id="camBadge">`，初始文字「相機初始化中…」
   - 一個 webhook 狀態徽章 `<span class="badge" id="hookBadge">`，初始文字「webhook 未設定」
2. `<main>`：兩欄式 grid，內含兩個 `.panel`（卡片）：
   - **左卡片「相機畫面」**：
     - `<h2>相機畫面</h2>`
     - 一個 `.stage`（黑底檯面）：內含 `<video id="video" autoplay playsinline muted>`、
       `<img id="photo" alt="拍攝結果">`（預設隱藏）、一個 `.shot-tag` 文字「已拍攝」（預設隱藏）、
       一個 `.hint` 覆蓋層 `<div id="camHint">`，初始文字「正在要求相機權限…」
     - `.controls`：兩顆按鈕 —
       - `<button class="btn-main" id="btnShot" disabled>📷 拍攝並記錄時間</button>`
       - `<button class="btn-ghost" id="btnRetake" disabled>重拍</button>`
   - **右卡片「拾獲資訊」**：
     - `<h2>拾獲資訊</h2>`
     - 「拾獲地點」欄位：一組地點快選 chips（單選 radio，`name="loc"`，`role="radiogroup"`），
       選項與 value 完全一致、順序不可變，依序為：
       共善樓、運動場、體育館、行政一館、行政二館、語文大樓、人社館、圖書館、丘逢甲紀念館、
       科航館、人言大樓、資電館、其他。
       「其他」被選到時，底下要浮出一個文字輸入框 `id="locOther"`，placeholder「請輸入地點」，
       `aria-label="其他地點"`，未選「其他」時用 `hidden` 屬性隱藏。
     - 「拾獲時間」欄位：`<input type="datetime-local" id="foundAt">`，下方一行說明文字：
       「按下拍攝鍵時會自動帶入當下時間，若不是當場撿到可以自己改。」
     - 「補充描述 — 選填」欄位：`<textarea id="desc">`，placeholder
       「例如：在二樓靠窗的座位撿到，傘柄有點磨損。」，下方說明文字：
       「物品是什麼可以交給照片辨識，這欄只要補充選項講不清楚的細節（確切位置、外觀特徵）就好。」
     - 一顆送出大按鈕：`<button class="btn-send" id="btnSend" disabled style="width:100%">送出</button>`
     - 一個狀態列 `<div id="status">`（預設不顯示，靠 class 切換顯示與配色）
     - 一個結果卡片 `<div id="result" class="panel">`：`<h2>n8n 回傳結果</h2>` +
       `<table id="resultTable">`（預設不顯示）
3. `<details class="cfg">`：整頁最底部、`<main>` 之外的設定折疊區，`<summary>` 文字
   「⚙️ 設定（webhook 位址 / 相機來源）」，展開後內容：
   - 一列（row）：`<label for="hookUrl">n8n Webhook URL</label>` +
     `<input type="text" id="hookUrl" placeholder="http://localhost:5678/webhook/lost-found">` +
     旁邊一顆 `<button class="btn-ghost" id="btnSaveHook">儲存</button>`
   - 一列：`<label for="camSelect">相機裝置</label>` + `<select id="camSelect">`
     （初始只有一個 `<option>載入中…</option>`）+ 旁邊一顆
     `<button class="btn-ghost" id="btnSwitchCam">切換</button>`
   - 一段說明文字（含 `<code>` 行內標籤）：
     「測試流程時把 n8n 的 workflow 切到「Execute workflow」聆聽模式，webhook 路徑要改成
     `/webhook-test/lost-found`；正式啟用（Active）後才是 `/webhook/lost-found`。」
4. 一個永遠隱藏、只當離屏繪圖緩衝用的 `<canvas id="canvas" hidden>`（不會顯示在畫面上，只用來把
   video 畫面截成圖片）。

## 3. 版面配置與 RWD

- `<main>` 用 CSS Grid：`grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr)`（左欄稍寬），
  `gap: 24px`，`align-items: start`，`max-width: 1440px`，置中（`margin: 0 auto`），
  `padding: 32px 24px 48px`。
- 斷點在 **833px**：`@media (max-width: 833px)` 時 `<main>` 改成單欄
  `grid-template-columns: 1fr`，padding 改為 `24px 17px 32px`。
- `<header>` 是 `position: sticky; top: 0; z-index: 20;`，`min-height: 48px`，
  `padding: 8px 22px`，flex 排列、允許 wrap、item 間 gap 12px。
- `.stage`（相機檯面）維持 `aspect-ratio: 4/3`。
- 設定區 `<details class="cfg">` 也是 `max-width: 1440px` 置中，`margin: 0 auto 48px`，
  左右 padding 在桌機是 24px、在 ≤833px 斷點改成 17px。
- 沒有任何 `position: fixed` 的浮動元件；整頁可以隨內容自然滾動，只有 header 是 sticky。

## 4. 視覺設計 Token（必須逐字採用下列數值，不可用「看起來類似」的顏色代替）

把下面這組 CSS 自訂屬性原封不動放進 `:root`：

```css
:root {
  /* 色彩 */
  --primary: #0066cc;          /* 全站唯一的互動色（連結、按鈕、focus 邊框、勾選態） */
  --primary-focus: #0071e3;    /* 鍵盤 focus ring / 選中態邊框 */
  --primary-on-dark: #2997ff;  /* 深色底上的連結藍（保留變數，即使目前沒有元件用到也要定義） */
  --ink: #1d1d1f;               /* 主要文字色 */
  --ink-muted-80: #333333;      /* 次要文字（code 內文用） */
  --ink-muted-48: #7a7a7a;      /* 說明文字 / disabled 文字 / placeholder */
  --body-on-dark: #ffffff;      /* 深色底上的白字（header 標題） */
  --body-muted: #cccccc;        /* 深色底上的次要文字（badge 預設色、相機提示文字） */
  --canvas: #ffffff;            /* 卡片、輸入框底色 */
  --parchment: #f5f5f7;         /* 全站頁面底色 */
  --pearl: #fafafc;             /* 定義但目前沒有任何選擇器使用，保留即可 */
  --surface-black: #000000;     /* header 與相機檯面的純黑 */
  --divider-soft: #f0f0f0;      /* code 標籤邊框 */
  --hairline: #e0e0e0;          /* 全站卡片／輸入框邊框色 */
  --chip-translucent: rgba(210, 210, 215, .64); /* 「已拍攝」浮貼標籤的毛玻璃底色 */
  --disabled-fill: #e8e8ed;     /* 按鈕 disabled 底色 */

  /* 狀態色（成功／錯誤／警示，各有一個一般態與一個深色底態） */
  --ok: #248a3d;        --ok-on-dark: #30d158;
  --err: #d70015;       --err-on-dark: #ff453a;
  --warn: #b25000;      --warn-on-dark: #ff9f0a;

  /* 圓角尺度 */
  --r-xs: 5px; --r-sm: 8px; --r-md: 11px; --r-lg: 18px; --r-pill: 9999px;

  /* 間距尺度 */
  --s-xxs: 4px; --s-xs: 8px; --s-sm: 12px; --s-md: 17px;
  --s-lg: 24px; --s-xl: 32px; --s-xxl: 48px; --s-section: 80px; /* s-section 目前沒被用到，保留 */

  /* 字型堆疊 */
  --font-text: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui,
               "PingFang TC", "Noto Sans TC", "Noto Sans CJK TC",
               "Microsoft JhengHei", sans-serif;
  --font-display: -apple-system, BlinkMacSystemFont, "SF Pro Display", system-ui,
                  "PingFang TC", "Noto Sans TC", "Noto Sans CJK TC",
                  "Microsoft JhengHei", sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;

  /* 全站唯一一道陰影，只給「放在檯面上的實體照片」使用 */
  --shadow-product: rgba(0, 0, 0, .22) 3px 5px 30px 0;
}
```

這是一個**單一亮色主題**，不需要做 `prefers-color-scheme` 深色模式；唯一出現「黑底」的地方是
header 與相機檯面，那是刻意的設計重音（模擬相機觀景窗），不是深色模式切換。

全站排版基準：`body { font-size: 17px; line-height: 1.47; letter-spacing: -.374px; }`，
`font-family` 用 `--font-text`；`-webkit-font-smoothing: antialiased`；`html, body` 都
`height: 100%`；`body` 底色是 `--parchment`，文字色 `--ink`。`* { box-sizing: border-box; }`。

標題字（`h1`、各 `.panel h2`、`#result h2`）一律用 `--font-display`，
`font-size: 17px; font-weight: 600; line-height: 1.24; letter-spacing: -.374px;`。

### 逐區塊樣式數值

- **header**：`background: var(--surface-black)`，文字色 `var(--body-on-dark)`。
- **.badge**：`font-size: 12px; line-height: 1.4; letter-spacing: -.12px; font-weight: 400;`，
  `padding: 3px 10px; border-radius: var(--r-pill);`，
  底色 `rgba(255,255,255,.08)`，邊框 `1px solid rgba(255,255,255,.16)`，文字色
  `var(--body-muted)`，`word-break: break-all`。
  - `.badge.live`：文字 `var(--ok-on-dark)`，邊框色 `rgba(48,209,88,.42)`。
  - `.badge.dead`：文字 `var(--err-on-dark)`，邊框色 `rgba(255,69,58,.42)`。
- **.panel**：底色 `var(--canvas)`，邊框 `1px solid var(--hairline)`，
  `border-radius: var(--r-lg)`（18px），`overflow: hidden`。
  - `.panel h2`：`padding: 20px var(--s-lg) 14px`（即 `20px 24px 14px`）。
  - `.panel .body`：`padding: 0 var(--s-lg) var(--s-lg)`（即 `0 24px 24px`）。
- **.stage**（相機檯面）：`background: var(--surface-black)`，`aspect-ratio: 4/3`，
  flex 置中，`transition: background-color .25s ease`。`video`/`img` 皆
  `width:100%; height:100%; object-fit: contain;`；`img` 預設 `display: none`。
  - 拍完照後 `body.shot` 生效：`.stage` 底色變 `var(--parchment)`，`padding: var(--s-lg)`；
    `video` 隱藏；`img` 顯示且改成 `width: auto; height: auto; max-width:100%; max-height:100%;`，
    `border-radius: var(--r-sm)`（8px），**加上全站唯一一道陰影**
    `box-shadow: var(--shadow-product)`（照片像放在檯面上的實體物）。
  - `.hint`：絕對定位鋪滿 `.stage`，flex 置中，`padding: var(--s-xl)`（32px），
    文字色 `var(--body-muted)`，`font-size:17px; line-height:1.47; letter-spacing:-.374px;`，
    底色 `var(--surface-black)`，`white-space: pre-wrap`；相機就緒（`body.cam-ok`）或已拍照
    （`body.shot`）時要隱藏這層提示。
  - `.shot-tag`：絕對定位 `left:16px; top:16px`，預設 `display:none`，拍完後
    （`body.shot`）顯示；底色 `var(--chip-translucent)`，`-webkit-backdrop-filter` /
    `backdrop-filter: saturate(180%) blur(20px)`，`padding: 6px 14px`，
    `border-radius: var(--r-pill)`，`font-size:14px; line-height:1.29; letter-spacing:-.224px;`，
    文字色 `var(--ink)`。
- **.controls**：`display:flex; gap: var(--s-sm); padding: 16px var(--s-lg) var(--s-lg); flex-wrap: wrap;`。
- **按鈕通則**（所有 `<button>`）：`font-family: var(--font-text); font-size:17px; font-weight:400;
  line-height:1.47; letter-spacing:-.374px;`，`border-radius: var(--r-pill)`（藥丸形），
  `border: 1px solid transparent;`，`padding:11px 22px; min-height:44px;`，
  `cursor:pointer; flex:1 1 auto;`，過場 `transition: background-color .15s ease, color .15s ease,
  border-color .15s ease, transform .12s ease;`。
  - **按壓微互動**（全站唯一的一種）：`button:not(:disabled):active { transform: scale(.95); }`
  - **鍵盤 focus**：`button:focus-visible { outline: 2px solid var(--primary-focus);
    outline-offset: 2px; }`
  - **disabled 態**：底色 `var(--disabled-fill)`，文字色 `var(--ink-muted-48)`，
    邊框透明，`cursor: default`。
  - `.btn-main`：底色 `var(--primary)`，文字色 `var(--canvas)`（白字藍底實心）。
  - `.btn-ghost`：透明底，文字色 `var(--primary)`，邊框色 `var(--primary)`（外框藍字）。
  - `.btn-send`：底色 `var(--primary)`，文字色 `var(--canvas)`，但比一般按鈕更醒目：
    `font-size:18px; font-weight:600; line-height:1;`，`padding:15px 28px; min-height:48px;`，
    `margin-top: var(--s-xxs)`（4px）。
- **表單通則**：`label`／`.label`：`display:block; font-size:14px; font-weight:600; line-height:1.29;
  letter-spacing:-.224px; color: var(--ink); margin-bottom: var(--s-xs);`（8px）。
  `.label .opt`（「— 選填」那種次要字樣）：`font-weight:400; color: var(--ink-muted-48);`。
  `textarea, input[type=text], input[type=datetime-local], select`：`width:100%;
  background: var(--canvas); color: var(--ink); border:1px solid var(--hairline);
  border-radius: var(--r-md);`（11px），`padding:12px 16px;`，字級同 body（17px / 1.47 /
  -.374px）。`input[type=datetime-local]` 額外 `max-width:300px;`。`textarea` 額外
  `min-height:140px; resize:vertical;`。
  - **focus 態**（textarea/input/select）：`outline:2px solid var(--primary-focus);
    outline-offset:-1px; border-color: var(--primary-focus);`
  - placeholder 顏色一律 `var(--ink-muted-48)`。
  - `.field { margin-bottom: var(--s-lg); }`（24px），`.field:last-child { margin-bottom:0; }`
  - `.example`：`font-size:14px; line-height:1.43; letter-spacing:-.224px;
    color: var(--ink-muted-48); margin-top: var(--s-xs);`（8px）。
  - `code`（行內標籤）：`font-family: var(--font-mono); font-size:.92em;
    background: var(--parchment); border:1px solid var(--divider-soft);
    border-radius: var(--r-xs); padding:1px 5px; color: var(--ink-muted-80);`
- **地點快選 chip**：外層 `.chips { display:flex; flex-wrap:wrap; gap: var(--s-xs); }`（8px 間距）。
  每顆 `.chip` 是把原生 `<input type=radio>` 蓋成絕對定位、透明、`opacity:0`、
  `pointer-events:none` 蓋在整顆 chip 上（純粹拿它的 checked 狀態），視覺全落在旁邊的
  `<span>` 上：
  - 未選中：`min-height:44px; padding:10px 18px;`，底色 `var(--canvas)`，文字色 `var(--ink)`，
    邊框 `1px solid var(--hairline)`，`border-radius: var(--r-pill)`，
    `font-size:14px; line-height:1.29; letter-spacing:-.224px;`，`cursor:pointer;
    user-select:none;`，過場 `border-color .15s ease, color .15s ease, transform .12s ease`。
  - 按下瞬間：`span:active { transform: scale(.95); }`（跟按鈕一樣的按壓手感）。
  - **選中態**（`input:checked + span`）：邊框變粗成 `2px solid var(--primary-focus)`，
    因此 padding 要相應內縮成 `9px 17px`（補償多出來的 1px 邊框，讓外觀尺寸不跳動），
    文字色變 `var(--primary)`，`font-weight:600`。
  - **鍵盤 focus**（`input:focus-visible + span`）：`outline:2px solid var(--primary-focus);
    outline-offset:2px;`
  - `#locOther`（其他地點文字框）：`max-width:320px; margin-top: var(--s-xs);`
- **#status**（狀態列）：`margin-top:16px; padding:14px 16px; border-radius: var(--r-md);
  font-size:14px; line-height:1.43; letter-spacing:-.224px; border:1px solid var(--hairline);
  background: var(--parchment); color: var(--ink-muted-80);`，預設 `display:none`，
  有 `.show` class 時才 `display:block`；`white-space:pre-wrap; word-break:break-word;`。
  三種語意 class 疊加在 `.show` 上：
  - `.ok`：邊框 `rgba(36,138,61,.32)`，底色 `rgba(36,138,61,.06)`，文字 `var(--ok)`。
  - `.err`：邊框 `rgba(215,0,21,.32)`，底色 `rgba(215,0,21,.05)`，文字 `var(--err)`。
  - `.busy`：邊框 `rgba(178,80,0,.32)`，底色 `rgba(178,80,0,.05)`，文字 `var(--warn)`。
- **#result**（回傳結果卡）：預設 `display:none`，有 `.show` 才顯示；`margin-top:16px;
  overflow:hidden; background: var(--parchment); border:1px solid var(--hairline);
  border-radius: var(--r-lg);`。內部 `h2`：`padding:16px 20px 10px;`。`table`：
  `width:100%; border-collapse:collapse;`。`th, td`：`text-align:left; padding:10px 20px;
  border-top:1px solid var(--hairline); vertical-align:top; font-size:14px; line-height:1.43;
  letter-spacing:-.224px;`。`th`：`color: var(--ink-muted-48); font-weight:600; width:34%;
  white-space:nowrap;`（key 欄）。`td`：`color: var(--ink); word-break:break-word;`（value 欄）。
  `a`（值若是網址）：`color: var(--primary); text-decoration:none;`
- **設定折疊區**：`summary`：`cursor:pointer; color: var(--primary); font-size:17px;
  line-height:1.47; letter-spacing:-.374px; padding:10px 0; user-select:none;`；
  focus-visible 時 `outline:2px solid var(--primary-focus); outline-offset:2px;
  border-radius: var(--r-xs);`。展開後的 `.box`：`background: var(--canvas);
  border:1px solid var(--hairline); border-radius: var(--r-lg); padding: var(--s-lg);
  margin-top: var(--s-xs);`。內部一列 `.row`：`display:flex; gap: var(--s-sm);
  align-items:flex-end; flex-wrap:wrap;`，`.row .grow { flex:1 1 320px; }`，
  `.row button`：`flex:0 0 auto; min-height:44px; padding:11px 22px; font-size:14px;
  line-height:1.29; letter-spacing:-.224px;`（比一般按鈕小一級的次要按鈕字級）。

## 5. 互動元件與行為（狀態機）

### 頁面啟動時（DOMContentLoaded / IIFE 執行時）
- 讀取 `localStorage` 裡的 webhook 網址（key 見第 7 節），畫出 hookBadge 與設定面板裡的
  `hookUrl` 輸入框初始值；若使用者沒存過，顯示預設值
  `http://localhost:5678/webhook/lost-found`。
- `foundAt` 輸入框先帶入「現在」的本地時間（`datetime-local` 格式 `YYYY-MM-DDTHH:mm`）。
- 立刻嘗試啟動相機（見第 6 節），優先用 `localStorage` 記住的上次相機 deviceId，沒有就用預設鏡頭。

### 拍攝按鈕（`btnShot`）
- 初始 `disabled`；相機成功取得畫面後才啟用。
- 點擊時：若 `video.videoWidth` 還是 0（畫面還沒真的吃到），顯示錯誤狀態
  「相機畫面還沒準備好，稍等一秒再按。」並中止。
- 否則：記錄「按下的當下」時間戳，把 `<video>` 目前畫面畫進離屏 `<canvas>`（尺寸取
  `video.videoWidth` / `videoHeight`），轉成 `image/jpeg`、品質 `0.85` 的 dataURL，切出 base64
  本體存起來；把 `<img id="photo">` 的 `src` 設成這個 dataURL；`body` 加上 `shot` class（觸發
  第 4 節那些「拍完後」的樣式）；**若使用者還沒手動改過「拾獲時間」欄位**，就把它自動帶入這個
  拍攝時間；啟用 `btnRetake` 與 `btnSend`；把自己（`btnShot`）disable 掉；清空狀態列與結果卡；
  把 focus 移到補充描述欄位（若存在）。

### 重拍按鈕（`btnRetake`）
- 初始 `disabled`，拍完照才啟用。
- 點擊時：清掉暫存的照片資料、移除 `body` 的 `shot` class（畫面切回即時 video）、重新 disable
  `btnRetake` 與 `btnSend`、重新 enable `btnShot`、清空狀態列與結果卡。

### 「拾獲時間」欄位
- 使用者只要手動輸入過這個欄位一次，就要記住「使用者已手動改過」；之後即使再按拍攝，也**不可以**
  再用拍攝時間覆蓋掉使用者填的值（一次性生效，程式生命週期內持續有效）。

### 地點 chips
- 選到「其他」時，`#locOther` 顯示（移除 `hidden`）並自動 focus；選其他項目時 `#locOther`
  要重新隱藏（加回 `hidden`）。

### 送出按鈕（`btnSend`）
- 初始 `disabled`，拍完照才啟用；送出過程中要 disable 掉 `btnSend`、`btnShot`、`btnRetake`
  三顆按鈕，避免使用者中途誤觸；送出結束（成功或失敗）後把它們的 disabled 狀態復原（成功時
  `btnSend` 仍維持 disabled，因為流程視為完成，但 `btnShot`／`btnRetake` 恢復可用；失敗時三顆
  都恢復可用讓使用者可以重試）。
- 點擊時依序做以下檢查，任何一項沒過就用 `setStatus('err', 訊息)` 顯示錯誤、把 focus 移到對應
  欄位、並中止流程（不送出）：
  1. 沒有照片 → 「請先按「拍攝並記錄時間」。」
  2. 選了「其他」但沒填地點 → 「選了「其他」，請在下方欄位填寫實際地點。」，focus 到
     `#locOther`。
  3. 完全沒選地點 → 「請先選擇拾獲地點。」，focus 到第一個地點 radio。
  4. 拾獲時間欄位空白或格式不合法 → 「請選擇拾獲時間。」，focus 到 `#foundAt`。
- 檢查都通過後：組出 JSON payload（見第 7 節），顯示忙碌狀態
  `setStatus('busy', '上傳中…（X KB 影像，LLM 辨識約需數秒）')`（X 是照片 base64 長度換算出的
  概略 KB 數，換算方式是 `Math.round(base64長度 / 1365)`），清空結果卡的顯示 class，然後用
  `fetch` POST 到 webhook 網址。
  - 回應非 2xx：丟出 `Error('n8n 回應 HTTP ' + 狀態碼 + '\n' + 回應內文前400字')`。
  - 回應內文能 `JSON.parse` 就當 JSON 用；不能就包成 `{ 回應: 內文前400字 }`。
  - 成功：`setStatus('ok', '✓ 已送出並寫入 Google Sheet。')`，呼叫渲染結果表格（見第 8 節），
    重新啟用 `btnRetake`／`btnShot`。
  - 失敗（含網路層失敗）：把錯誤訊息組成 `'✗ 送出失敗\n' + 錯誤訊息`；如果錯誤訊息裡含
    `Failed to fetch`，要在後面加一段除錯提示：
    ```
    可能原因：
    · webhook URL 不對或 workflow 沒啟用（Active）
    · n8n Webhook 節點沒開 CORS：Options → Allowed Origins (CORS) 設成 *
    · 測試模式要用 /webhook-test/ 路徑，且要先按 Execute workflow
    ```
    用 `setStatus('err', ...)` 顯示，並把三顆按鈕都恢復可用。

### 設定面板
- 「儲存」按鈕（`btnSaveHook`）：把 `hookUrl` 輸入框的值 trim 後存進 `localStorage`；若清空就
  改成移除該 key（回退成預設值）；重畫 hookBadge；顯示 `setStatus('ok', 'Webhook 位址已儲存。')`。
- 「切換」按鈕（`btnSwitchCam`）：取 `camSelect` 目前選到的 deviceId，存進 `localStorage`，
  用這個 deviceId 重新啟動相機。
- hookBadge 顯示規則：文字內容是把網址開頭的 `http://` 或 `https://` 去掉後的字串；只要有網址
  就加上 `live` 這個 class（不像相機徽章有 dead 狀態的判斷邏輯，這裡只要非空字串就視為 live）。

## 6. 相機邏輯

- 用 `navigator.mediaDevices.getUserMedia` 取得畫面；若瀏覽器完全不支援
  （沒有 `navigator.mediaDevices` 或沒有 `getUserMedia`），camBadge 顯示「瀏覽器不支援」
  （dead 樣式），提示文字「這個瀏覽器沒有 getUserMedia。請用 Chromium 或 Firefox 開啟。」，
  之後不再嘗試。
- 呼叫前先把 camBadge 重置成「相機初始化中…」（一般樣式）。
- constraints：
  ```js
  var constraints = {
    audio: false,
    video: deviceId
      ? { deviceId: { exact: deviceId } }
      : { width: { ideal: 1280 }, height: { ideal: 720 } }
  };
  ```
  也就是：預設（沒有指定 deviceId 時）用 1280×720 的理想解析度、不指定鏡頭；使用者從設定面板
  切換過某顆鏡頭之後，改用 `exact` deviceId 指定那顆鏡頭（不再帶解析度限制）。
- 成功拿到 stream：接上 `<video>` 的 `srcObject`；`body` 加上 `cam-ok` class（隱藏 hint 覆蓋層）；
  啟用 `btnShot`；讀這顆視訊軌的 `getSettings()`，把 camBadge 文字改成
  「相機就緒」，若拿得到寬高再加上 `' · ' + 寬 + '×' + 高`；camBadge 套 `live` 樣式；把這顆
  鏡頭的 deviceId 存進 `localStorage`（供下次啟動沿用）；接著列舉所有鏡頭裝置填入
  `camSelect` 下拉選單（`enumerateDevices()`，只取 `kind === 'videoinput'` 的裝置，選項文字
  用裝置的 `label`，沒有 label 就顯示「相機 N」；若目前用的 deviceId 對得上某個選項就把它設
  selected；完全沒有鏡頭時顯示唯一一個選項「找不到相機」）。
- 失敗（`.catch`）：`body` 移除 `cam-ok`；`btnShot` 重新 disable；camBadge 顯示「相機失敗」
  （dead 樣式）；提示文字固定開頭是 `'無法開啟相機：' + err.name + '\n'`，再依錯誤類型附加：
  - `NotAllowedError` → 「權限被拒。請在網址列左側的鎖頭圖示允許相機存取後重新整理。」
  - `NotFoundError` → 「找不到任何相機裝置，確認 USB webcam 有接好（/dev/video0）。」
  - `NotReadableError` → 「裝置被其他程式占用，關掉其他正在用相機的程式再試。」
  - 否則，若目前**不是** secure context（`location.protocol !== 'https:'` 且
    hostname 不是 `localhost`／`127.0.0.1`）→
    「目前不是安全來源（secure context）。請用 http://localhost 開啟，不要用 file:// 或
    區網 IP。」
  （這四種是互斥的 if/else if，只會顯示對應到的那一句，不會疊加）
- 切換相機或重新啟動相機前，一定要先把舊的 `MediaStream` 的所有 track `stop()` 掉再要新的，
  避免鏡頭一直被佔用。

## 7. 送出的 JSON payload（欄位名稱與型別必須完全一致，不可增減、不可改名）

送出前先把使用者選的地點與時間組成一段結構化文字（讓 n8n 端的「結構化抽取」不必用猜的）：

```
【拾獲地點】<地點值>
【拾獲時間】<YYYY-MM-DD HH:mm 格式的拾獲時間>
【拾獲者補充】<使用者填的補充描述，若補充描述為空就不要有這一行>
```
三行用 `\n` 相接（若沒有補充描述就只有前兩行）。

實際 POST 的 JSON 物件（`Content-Type: application/json`，POST 到使用者設定的 webhook 網址）：

```js
{
  capturedAt:        isoLocal(found),        // 拾獲時間的本地 ISO 8601（含時區位移），
                                              // 例如 "2026-08-15T23:45:12+08:00"
  capturedAtDisplay: extractFormat(found),   // 拾獲時間，格式 "YYYY-MM-DD HH:mm"
  capturedAtEpoch:   found.getTime(),        // 拾獲時間的毫秒 epoch
  timezone:          Intl 取得的 IANA 時區字串（取不到就空字串）,
  description:       text,                  // 上面組出的【拾獲地點】/【拾獲時間】/【拾獲者補充】結構化文字
  foundLocation:     loc.value,             // 拾獲地點原始值（明確欄位，方便 n8n 直接取用）
  foundAt:           isoLocal(found),       // 與 capturedAt 相同值
  foundAtDisplay:    extractFormat(found),  // 與 capturedAtDisplay 相同值
  note:              note,                  // 使用者實際打的補充描述原文（不含前綴標籤）
  fileName:          shot.fileName,         // 例如 "lostfound-20260815-234512.jpg"
  mimeType:          'image/jpeg',
  imageBase64:       shot.base64            // 純 base64（已去掉 data:image/jpeg;base64, 前綴）
}
```

**特別注意**：`capturedAt` / `capturedAtDisplay` / `capturedAtEpoch` 這三個欄位名稱看起來像是
「拍照當下時間」，但**值一律用「拾獲時間」**（不是真正按下快門的時間）——保留這三個 key 名是為了
相容既有的 n8n workflow（它讀的是 `body.capturedAtDisplay`），只是把值改填成使用者確認過的拾獲
時間。`found` 是使用者在「拾獲時間」欄位選定、解析出來的 `Date` 物件（用正則手動解析
`YYYY-MM-DDTHH:mm` 字串自己組 `new Date(年,月-1,日,時,分,0,0)`，刻意不要直接把字串丟給
`new Date(字串)`，因為不同瀏覽器引擎對「沒有時區資訊的字串」解讀不一致）。

檔名格式函式：`'lostfound-' + YYYY + MM + DD + '-' + HH + MM + SS + '.jpg'`（月、日、時、分、秒
皆補零至 2 位）。

## 8. n8n 回傳結果的渲染規則

- 回應本體若是陣列，取第一個元素；若該物件底下有一個 `json` 子物件（n8n 常見的輸出包裝），
  要再往下取一層，用 `obj.json` 當作真正要顯示的資料。
- 把這個物件的每一個 key 各畫成 `<table>` 的一列：`<th>` 放 key 原文，`<td>` 放 value；
  value 是字串且長得像 `http://` 或 `https://` 開頭的網址時，要渲染成可點擊的
  `<a href="值" target="_blank" rel="noopener">值</a>`；value 是 `null`/`undefined` 顯示空字串；
  是物件則用 `JSON.stringify` 轉成字串顯示；其餘用 `String()` 轉字串顯示。
- 物件完全沒有任何 key 時，不要顯示這個結果卡（維持隱藏）。
- 渲染完成後把結果卡的 class 設為 `panel show` 讓它顯示出來。

## 9. localStorage 使用（key 名稱必須完全一致）

- `lostfound.webhookUrl`：使用者自訂的 webhook 網址；沒有值時預設用
  `http://localhost:5678/webhook/lost-found`。
- `lostfound.deviceId`：使用者上次選定/切換到的相機 deviceId；下次開啟頁面優先用這顆鏡頭。

## 10. 文案總表（畫面上會出現的中文字串，逐字照抄，不可意譯或改寫）

- 分頁標題：失物招領登錄
- 頂欄標題：失物招領登錄
- 相機徽章初始值：相機初始化中…
- 相機徽章其他狀態：相機就緒（可能接 " · 寬×高"）／相機失敗／瀏覽器不支援
- webhook 徽章初始值：webhook 未設定
- 左卡片標題：相機畫面
- 相機提示初始文字：正在要求相機權限…
- 已拍攝浮貼：已拍攝
- 拍攝按鈕：📷 拍攝並記錄時間
- 重拍按鈕：重拍
- 右卡片標題：拾獲資訊
- 地點欄標題：拾獲地點
- 地點選項（依序）：共善樓／運動場／體育館／行政一館／行政二館／語文大樓／人社館／圖書館／
  丘逢甲紀念館／科航館／人言大樓／資電館／其他
- 其他地點輸入框 placeholder：請輸入地點
- 拾獲時間欄標題：拾獲時間
- 拾獲時間說明：按下拍攝鍵時會自動帶入當下時間，若不是當場撿到可以自己改。
- 補充描述欄標題：補充描述（後接較淡字樣「 — 選填」）
- 補充描述 placeholder：例如：在二樓靠窗的座位撿到，傘柄有點磨損。
- 補充描述說明：物品是什麼可以交給照片辨識，這欄只要補充選項講不清楚的細節（確切位置、外觀
  特徵）就好。
- 送出按鈕：送出
- 結果卡標題：n8n 回傳結果
- 設定區收合標題：⚙️ 設定（webhook 位址 / 相機來源）
- webhook 網址欄標題：n8n Webhook URL
- webhook 網址 placeholder：http://localhost:5678/webhook/lost-found
- 儲存按鈕：儲存
- 相機裝置欄標題：相機裝置
- 相機下拉初始選項：載入中…
- 找不到鏡頭時：找不到相機
- 切換按鈕：切換
- 設定區說明（含行內 code）：測試流程時把 n8n 的 workflow 切到「Execute workflow」聆聽模式，
  webhook 路徑要改成 `/webhook-test/lost-found`；正式啟用（Active）後才是
  `/webhook/lost-found`。
- 相機錯誤（不支援）：這個瀏覽器沒有 getUserMedia。請用 Chromium 或 Firefox 開啟。
- 相機錯誤（權限被拒）：權限被拒。請在網址列左側的鎖頭圖示允許相機存取後重新整理。
- 相機錯誤（找不到裝置）：找不到任何相機裝置，確認 USB webcam 有接好（/dev/video0）。
- 相機錯誤（裝置被占用）：裝置被其他程式占用，關掉其他正在用相機的程式再試。
- 相機錯誤（非 secure context）：目前不是安全來源（secure context）。請用 http://localhost
  開啟，不要用 file:// 或區網 IP。
- 拍攝時機未就緒錯誤：相機畫面還沒準備好，稍等一秒再按。
- 送出前檢查：未拍照：請先按「拍攝並記錄時間」。
- 送出前檢查：其他地點未填：選了「其他」，請在下方欄位填寫實際地點。
- 送出前檢查：未選地點：請先選擇拾獲地點。
- 送出前檢查：時間未選：請選擇拾獲時間。
- 送出中狀態：上傳中…（X KB 影像，LLM 辨識約需數秒）
- 送出成功狀態：✓ 已送出並寫入 Google Sheet。
- 送出失敗狀態前綴：✗ 送出失敗
- Failed to fetch 附加除錯提示（原文照抄，含項目符號 `·`）：
  ```
  可能原因：
  · webhook URL 不對或 workflow 沒啟用（Active）
  · n8n Webhook 節點沒開 CORS：Options → Allowed Origins (CORS) 設成 *
  · 測試模式要用 /webhook-test/ 路徑，且要先按 Execute workflow
  ```
- webhook 儲存成功狀態：Webhook 位址已儲存。

## 11. 給你（實作者）的完成標準

輸出必須是**一個完整、可以直接存成 index.html、用 `python3 -m http.server` 服務後在
`http://localhost:PORT` 打開就能跑的檔案**。打開後應該：相機自動要求權限並顯示畫面、拍照後照片
浮貼在淺色檯面上並帶陰影、可以選地點/填時間/填描述、送出會打上面規格的 JSON 到 webhook 網址、
回傳結果能整齊列表顯示。除了以上規格外的任何細節（例如你怎麼組織 JS 函式、變數命名）都可以照你
自己的判斷寫，但**視覺數值、文案字串、JSON 欄位名、localStorage key 名這四類，一律不可偏離本
規格書**。

