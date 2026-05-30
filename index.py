from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google.genai import types, Client
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Eatficiency Backend API", version="1.1")

# --- 設定與初始化 ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
# 固定使用 gemini-2.5-flash-lite，不要再換了! 
MODEL_NAME = 'gemini-2.5-flash-lite'

# 初始化 Gemini
client = Client(api_key=GOOGLE_API_KEY)

# --- Google Sheets 授權 ---
def get_sheet_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    # 這裡假設你的 Service Account JSON 存在環境變數中或檔案中
    creds_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
    if creds_json:
        try:
            # 處理 .env 可能帶有的首尾單引號或空格
            creds_json = creds_json.strip()
            if creds_json.startswith("'") and creds_json.endswith("'"):
                creds_json = creds_json[1:-1]
            
            creds_dict = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        except json.JSONDecodeError as e:
            detail_msg = (
                f"❌ GOOGLE_SHEETS_CREDENTIALS 解析失敗: {e}\n"
                "原因可能是 .env 內容不是標準 JSON 格式。\n"
                "請確保內部所有鍵值對都使用雙引號 (\")，且私鑰中的換行符號已轉義為 \\n。"
            )
            print(detail_msg)
            raise HTTPException(status_code=500, detail=detail_msg)
    else:
        # 檢查本地檔案是否存在
        if not os.path.exists("service_account.json"):
            raise FileNotFoundError("找不到 service_account.json 且環境變數 GOOGLE_SHEETS_CREDENTIALS 未設定")
        creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
    return gspread.authorize(creds)

def get_worksheet(name: str):
    try:
        gc = get_sheet_client()
        sh = gc.open_by_key(SHEET_ID)
        return sh.worksheet(name)
    except gspread.exceptions.SpreadsheetNotFound:
        raise HTTPException(status_code=500, detail=f"找不到 ID 為 {SHEET_ID} 的試算表。請確認 ID 是否正確且已分享給 Service Account。")
    except gspread.exceptions.WorksheetNotFound:
        raise HTTPException(status_code=500, detail=f"試算表內找不到名為 '{name}' 的工作表。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google Sheets 存取失敗: {str(e)}")

@app.on_event("startup")
async def startup_event():
    print("\n🚀 正在檢查 Google Sheets 連線狀態...")
    try:
        get_worksheet("User_Data")
        print("✅ Google Sheets 連線成功！\n")
    except Exception as e:
        print(f"❌ Google Sheets 連線失敗: {e}\n")

# --- 資料模型 (Pydantic) ---
class ExpenseItem(BaseModel):
    user_name: str
    date: str
    foodname: str
    amount: int
    category: str
    calories: int
    health_score: int
    advice: str

class AnalysisRequest(BaseModel):
    text: Optional[str] = None
    user_name: str

# --- API 端點 ---

@app.get("/", include_in_schema=False)
def root():
    """回傳全功能的 Streamlit-like 網頁介面"""
    html_content = """
    <!DOCTYPE html>
    <html>
        <head>
            <title>Eatficiency Dashboard</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
            <style>
                html { font-size: 16px; -webkit-text-size-adjust: 100%; }
                @media (max-width: 640px) { html { font-size: 14px; } }
                .loading { border-top-color: #3498db; animation: spinner 1.5s linear infinite; }
                @keyframes spinner { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
                .tab-active { @apply bg-indigo-800 text-white shadow-inner; }
                .sidebar-item { @apply flex items-center space-x-3 px-4 py-3 rounded-xl transition-all cursor-pointer hover:bg-indigo-800/50; }
             </style>
        </head>
        <body class="bg-slate-50 min-h-screen font-sans text-slate-900 flex overflow-x-hidden">
            <!-- Mobile Sidebar Overlay -->
            <div id="sidebarOverlay" onclick="toggleSidebar()" class="fixed inset-0 bg-indigo-950/50 z-40 hidden lg:hidden backdrop-blur-sm transition-opacity"></div>

            <!-- Sidebar -->
            <aside id="sidebar" class="fixed inset-y-0 left-0 w-72 bg-indigo-900 text-indigo-100 flex flex-col shadow-2xl z-50 transform -translate-x-full lg:translate-x-0 lg:static lg:inset-0 transition-transform duration-300 ease-in-out">
                <div class="p-8 flex justify-between items-center">
                    <h1 class="text-2xl font-black tracking-tighter text-white flex items-center">
                        <i class="fa-solid fa-utensils mr-3 text-emerald-400"></i>EATFICIENCY
                    </h1>
                    <button onclick="toggleSidebar()" class="lg:hidden text-white/50 hover:text-white"><i class="fa-solid fa-xmark text-xl"></i></button>
                </div>
                
                <nav class="flex-1 px-4 space-y-2">
                    <div onclick="showTab('analyze')" id="menu-analyze" class="sidebar-item tab-active">
                        <i class="fa-solid fa-house-chimney w-6 text-center"></i>
                        <span class="font-bold">辨識儀表板</span>
                    </div>
                    <div onclick="showTab('history')" id="menu-history" class="sidebar-item">
                        <i class="fa-solid fa-clock-rotate-left w-6 text-center"></i>
                        <span class="font-bold">歷史足跡</span>
                    </div>
                </nav>

                <div class="p-6 mt-auto border-t border-indigo-800/50 bg-indigo-950/30">
                    <p class="text-xs font-black uppercase text-indigo-400 mb-4 tracking-widest">當前使用者</p>
                    <div class="space-y-3">
                        <select id="userSelect" class="w-full bg-indigo-800 text-white px-3 py-2 rounded-lg text-base border-none shadow-inner focus:ring-2 focus:ring-emerald-400"></select>
                        <button onclick="addUser()" class="w-full bg-emerald-500 px-4 py-2 rounded-lg text-sm font-black text-white hover:bg-emerald-400 transition-all shadow-lg"><i class="fa-solid fa-plus mr-1"></i>新增用戶</button>
                    </div>
                </div>
            </aside>

            <!-- Main Content -->
            <main class="flex-1 overflow-y-auto h-screen relative w-full">
                <!-- Mobile Header -->
                <div class="lg:hidden bg-indigo-900 text-white p-4 flex items-center justify-between sticky top-0 z-30 shadow-md">
                    <button onclick="toggleSidebar()" class="p-2 hover:bg-indigo-800 rounded-lg"><i class="fa-solid fa-bars text-xl"></i></button>
                    <span class="font-black tracking-tighter">EATFICIENCY</span>
                    <div class="w-10"></div> <!-- Placeholder for balance -->
                </div>

                <!-- Analyze Tab -->
                <div id="tab-analyze" class="tab-content p-5 md:p-10 space-y-8 animate-in fade-in duration-500">
                    <header class="flex justify-between items-end">
                        <div>
                            <h2 class="text-2xl md:text-3xl font-black text-slate-800">辨識儀表板</h2>
                            <p class="text-slate-400 font-medium">即時分析您的飲食與預算狀態</p>
                        </div>
                    </header>

                    <!-- 預算概覽卡片 -->
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                        <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 relative overflow-hidden group">
                            <div class="absolute top-0 right-0 p-4 opacity-10 group-hover:scale-110 transition-transform"><i class="fa-solid fa-wallet text-6xl"></i></div>
                            <p class="text-slate-500 text-sm font-bold uppercase tracking-wider">本月預算</p>
                            <h3 id="budgetLimit" class="text-2xl font-black text-slate-800 mt-1">$0</h3>
                            <button onclick="setBudget()" class="mt-4 text-indigo-600 hover:text-indigo-800 text-sm font-black"><i class="fa-solid fa-pen mr-1"></i>調整限額</button>
                        </div>
                        <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 relative overflow-hidden group">
                            <div class="absolute top-0 right-0 p-4 opacity-10 group-hover:scale-110 transition-transform"><i class="fa-solid fa-cart-shopping text-6xl text-rose-500"></i></div>
                            <p class="text-slate-500 text-sm font-bold uppercase tracking-wider">已支出</p>
                            <h3 id="budgetSpent" class="text-2xl font-black text-rose-500 mt-1">$0</h3>
                        </div>
                        <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 relative overflow-hidden group">
                            <div class="absolute top-0 right-0 p-4 opacity-10 group-hover:scale-110 transition-transform"><i class="fa-solid fa-leaf text-6xl text-emerald-500"></i></div>
                            <p class="text-slate-500 text-sm font-bold uppercase tracking-wider">剩餘預算</p>
                            <h3 id="budgetRemaining" class="text-2xl font-black text-emerald-500 mt-1">$0</h3>
                        </div>
                    </div>

                    <div class="grid grid-cols-1 lg:grid-cols-12 gap-8">
                        <!-- AI 建議區 (第2項) -->
                        <div class="lg:col-span-6 space-y-6">
                            <div class="bg-gradient-to-br from-indigo-600 to-indigo-800 p-8 rounded-[2.5rem] shadow-xl text-white relative overflow-hidden">
                                <div class="relative z-10">
                                    <h2 class="text-2xl font-black mb-2 flex items-center"><i class="fa-solid fa-lightbulb mr-3 text-yellow-300"></i>AI 飲食財務管家</h2>
                                    <p class="text-indigo-100 text-sm mb-6">基於您的歷史數據，生成深度分析建議</p>
                                    
                                    <div id="aiAdvicePlaceholder" class="bg-indigo-950/20 p-6 rounded-2xl border border-indigo-400/30 text-center">
                                        <p class="text-indigo-200 text-sm mb-4">點擊按鈕，讓 AI 為您的生活品質把關</p>
                                        <button onclick="loadAIAdvice()" class="bg-white text-indigo-700 px-6 py-3 rounded-xl font-black hover:bg-indigo-50 transition-all shadow-xl">獲取個人化分析</button>
                                    </div>

                                    <div id="aiAdviceContent" class="hidden space-y-4 animate-in slide-in-from-bottom-4 duration-700 max-h-[350px] overflow-y-auto pr-2">
                                        <div class="bg-white/10 p-5 rounded-2xl border border-white/10 backdrop-blur-md">
                                            <p class="text-sm font-black text-indigo-300 uppercase tracking-tighter mb-2">核心總結</p>
                                            <p id="aiSummary" class="text-lg font-bold leading-snug"></p>
                                        </div>
                                        <div class="bg-white/10 p-5 rounded-2xl border border-white/10 backdrop-blur-md">
                                            <p class="text-sm font-black text-indigo-300 uppercase tracking-tighter mb-2">深入分析</p>
                                            <p id="aiReason" class="text-base text-indigo-50 font-medium leading-relaxed"></p>
                                        </div>
                                        <button onclick="loadAIAdvice()" class="w-full py-3 text-xs font-bold text-indigo-300 hover:text-white transition-all text-center">重新分析 <i class="fa-solid fa-arrows-rotate ml-1"></i></button>
                                    </div>

                                    <div id="aiAdviceLoader" class="hidden flex flex-col items-center justify-center p-10">
                                        <div class="loading w-10 h-10 border-4 border-indigo-400/30 rounded-full mb-4"></div>
                                        <p class="text-xs font-bold text-indigo-300 animate-pulse">AI 正在翻閱您的紀錄...</p>
                                    </div>
                                </div>
                                <i class="fa-solid fa-brain absolute -bottom-10 -right-10 text-[15rem] text-white/5"></i>
                            </div>
                        </div>

                        <!-- 辨識功能輸入區 (擺在第2項下方) -->
                        <div class="lg:col-span-6 space-y-6">
                            <div class="bg-white p-8 rounded-[2.5rem] shadow-xl border border-slate-100">
                                <h2 class="text-2xl font-black mb-6 text-slate-800 flex items-center"><i class="fa-solid fa-robot mr-3 text-indigo-500"></i>AI 智能辨識</h2>
                                <div class="space-y-5">
                                    <div>
                                        <label class="block text-xs font-black text-slate-400 uppercase mb-2 tracking-widest">文字描述 (選填)</label>
                                        <input type="text" id="textInput" class="w-full bg-slate-50 border-none ring-1 ring-slate-200 focus:ring-2 focus:ring-indigo-500 p-4 rounded-2xl transition-all" placeholder="例如：午餐吃雞腿便當 120 元">
                                    </div>
                                    <div>
                                        <label class="block text-xs font-black text-slate-400 uppercase mb-2 tracking-widest">上傳圖片</label>
                                        <input type="file" id="fileInput" class="w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-6 file:rounded-full file:border-0 file:text-xs file:font-black file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100 transition-all cursor-pointer">
                                    </div>
                                    <button onclick="analyze()" id="btnAnalyze" class="w-full bg-indigo-600 text-white py-5 rounded-2xl font-black hover:bg-indigo-700 transition-all shadow-lg shadow-indigo-200 active:scale-95">開始 AI 辨識</button>
                                </div>

                                <div id="loader" class="hidden flex justify-center mt-6">
                                    <div class="loading w-10 h-10 border-4 border-indigo-200 rounded-full"></div>
                                </div>

                                <!-- 辨識結果表單 -->
                                <div id="resultCard" class="hidden mt-8 p-8 rounded-3xl bg-indigo-50/50 border border-indigo-100">
                                    <h3 class="font-black text-indigo-700 mb-6 flex items-center text-lg"><i class="fa-solid fa-wand-magic-sparkles mr-2"></i>確認辨識結果</h3>
                                    <div class="grid grid-cols-2 gap-4 text-sm">
                                        <div class="col-span-2"><label class="text-xs font-bold text-indigo-400 uppercase">品名</label><input id="edit_foodname" class="w-full p-3 rounded-xl border-none ring-1 ring-indigo-100 focus:ring-2 focus:ring-indigo-500 text-base"></div>
                                        <div><label class="text-xs font-bold text-indigo-400 uppercase">金額</label><input type="number" id="edit_amount" class="w-full p-3 rounded-xl border-none ring-1 ring-indigo-100 focus:ring-2 focus:ring-indigo-500 text-base"></div>
                                        <div><label class="text-xs font-bold text-indigo-400 uppercase">分類</label><input id="edit_category" class="w-full p-3 rounded-xl border-none ring-1 ring-indigo-100 focus:ring-2 focus:ring-indigo-500 text-base"></div>
                                        <div class="col-span-2"><label class="text-xs font-bold text-indigo-400 uppercase">AI 建議</label><textarea id="edit_advice" class="w-full p-3 rounded-xl border-none ring-1 ring-indigo-100 focus:ring-2 focus:ring-indigo-500 h-24 text-base"></textarea></div>
                                    </div>
                                    <button onclick="saveResult()" class="mt-6 w-full bg-emerald-500 text-white py-4 rounded-2xl font-black hover:bg-emerald-600 transition-all shadow-lg">確認並儲存</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- History Tab -->
                <div id="tab-history" class="tab-content hidden p-4 md:p-10 space-y-8 animate-in fade-in duration-500">
                    <header>
                        <h2 class="text-2xl md:text-3xl font-black text-slate-800">歷史足跡</h2>
                        <p class="text-slate-400 font-medium">回顧您的每一筆飲食支出與健康分數</p>
                    </header>

                    <div class="bg-white p-8 rounded-[2.5rem] shadow-xl border border-slate-100 overflow-hidden">
                        <div class="flex justify-between items-center mb-8">
                            <div class="flex space-x-2">
                                <span class="bg-indigo-50 text-indigo-600 px-4 py-1 rounded-full text-xs font-black border border-indigo-100">所有紀錄</span>
                            </div>
                            <button onclick="loadHistory()" class="text-indigo-600 text-sm font-bold hover:bg-indigo-50 px-4 py-2 rounded-xl transition-all"><i class="fa-solid fa-rotate mr-2"></i>重新整理</button>
                        </div>
                        <div class="overflow-x-auto">
                            <table class="w-full text-left border-collapse">
                                <thead class="hidden md:table-header-group">
                                    <tr class="border-b-2 border-slate-50 text-slate-400">
                                        <th class="pb-4 font-black uppercase text-xs tracking-widest">日期</th>
                                        <th class="pb-4 font-black uppercase text-xs tracking-widest">品名</th>
                                        <th class="pb-4 font-black uppercase text-xs tracking-widest text-right">金額</th>
                                        <th class="pb-4 font-black uppercase text-xs tracking-widest px-6">AI 飲食評價</th>
                                    </tr>
                                </thead>
                                <tbody id="historyBody" class="divide-y divide-slate-50"></tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </nav>

            <script>
                let currentResult = null;

                function toggleSidebar() {
                    const sidebar = document.getElementById('sidebar');
                    const overlay = document.getElementById('sidebarOverlay');
                    const isHidden = sidebar.classList.contains('-translate-x-full');
                    
                    if (isHidden) {
                        sidebar.classList.remove('-translate-x-full');
                        overlay.classList.remove('hidden');
                    } else {
                        sidebar.classList.add('-translate-x-full');
                        overlay.classList.add('hidden');
                    }
                }

                function showTab(tabName) {
                    document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
                    document.getElementById(`tab-${tabName}`).classList.remove('hidden');
                    
                    document.querySelectorAll('.sidebar-item').forEach(el => el.classList.remove('tab-active'));
                    document.getElementById(`menu-${tabName}`).classList.add('tab-active');
                    
                    // 手機版切換分頁後自動收合
                    if (window.innerWidth < 1024) toggleSidebar();
                }

                async function loadUsers() {
                    try {
                        const res = await fetch('/users');
                        const users = await res.json();
                        const select = document.getElementById('userSelect');
                        select.innerHTML = users.map(u => `<option value="${u}">${u}</option>`).join('');
                        if(users.length > 0) {
                            loadHistory();
                            loadBudget();
                            resetAIAdvice();
                        }
                    } catch(e) { console.error("Load users failed"); }
                }

                async function addUser() {
                    const name = prompt("請輸入新使用者名稱:");
                    if(name) {
                        await fetch(`/users/${name}`, { method: 'POST' });
                        loadUsers();
                    }
                }

                async function setBudget() {
                    const user = document.getElementById('userSelect').value;
                    const amount = prompt("請輸入本月預算上限:");
                    if(amount) {
                        await fetch(`/budget`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({user_name: user, budget_limit: parseInt(amount)}) });
                        loadBudget();
                    }
                }

                async function analyze() {
                    const user = document.getElementById('userSelect').value;
                    const text = document.getElementById('textInput').value;
                    const file = document.getElementById('fileInput').files[0];
                    const btn = document.getElementById('btnAnalyze');
                    
                    const formData = new FormData();
                    formData.append('user_name', user);
                    if(text) formData.append('text', text);
                    if(file) formData.append('file', file);

                    btn.disabled = true;
                    document.getElementById('loader').classList.remove('hidden');
                    
                    try {
                        const res = await fetch('/analyze', { method: 'POST', body: formData });
                        currentResult = await res.json();
                        
                        // 填入可編輯表單
                        document.getElementById('edit_foodname').value = currentResult.foodname || "";
                        document.getElementById('edit_amount').value = currentResult.amount || 0;
                        document.getElementById('edit_category').value = currentResult.category || "其他";
                        document.getElementById('edit_advice').value = currentResult.advice || "";
                        
                        document.getElementById('resultCard').classList.remove('hidden');
                        document.getElementById('resultCard').scrollIntoView({ behavior: 'smooth' });
                    } catch (e) { alert("辨識失敗"); }
                    
                    btn.disabled = false;
                    document.getElementById('loader').classList.add('hidden');
                }

                async function saveResult() {
                    const user = document.getElementById('userSelect').value;
                    const data = { 
                        user_name: user,
                        date: currentResult.date || new Date().toISOString().split('T')[0],
                        foodname: document.getElementById('edit_foodname').value,
                        amount: parseInt(document.getElementById('edit_amount').value),
                        category: document.getElementById('edit_category').value,
                        calories: currentResult.calories || 0,
                        health_score: currentResult.health_score || 5,
                        advice: document.getElementById('edit_advice').value
                    };
                    const res = await fetch('/expenses', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });
                    if(res.ok) {
                        alert("儲存成功！");
                        document.getElementById('resultCard').classList.add('hidden');
                        loadHistory();
                        loadBudget();
                    }
                }

                async function loadBudget() {
                    const user = document.getElementById('userSelect').value;
                    const res = await fetch(`/budget/${user}`);
                    const data = await res.json();
                    document.getElementById('budgetLimit').innerText = `$${data.limit.toLocaleString()}`;
                    document.getElementById('budgetSpent').innerText = `$${data.spent.toLocaleString()}`;
                    document.getElementById('budgetRemaining').innerText = `$${data.remaining.toLocaleString()}`;
                }

                function resetAIAdvice() {
                    document.getElementById('aiAdvicePlaceholder').classList.remove('hidden');
                    document.getElementById('aiAdviceContent').classList.add('hidden');
                    document.getElementById('aiAdviceLoader').classList.add('hidden');
                }

                async function loadAIAdvice() {
                    const user = document.getElementById('userSelect').value;
                    const placeholder = document.getElementById('aiAdvicePlaceholder');
                    const loader = document.getElementById('aiAdviceLoader');
                    const content = document.getElementById('aiAdviceContent');

                    placeholder.classList.add('hidden');
                    loader.classList.remove('hidden');
                    content.classList.add('hidden');

                    try {
                        const res = await fetch(`/overall-advice/${user}`);
                        const data = await res.json();
                        document.getElementById('aiSummary').innerText = data.analysis.summary;
                        document.getElementById('aiReason').innerText = data.analysis.reason;
                        loader.classList.add('hidden');
                        content.classList.remove('hidden');
                    } catch(e) { alert("AI 分析失敗"); resetAIAdvice(); }
                }

                async function loadHistory() {
                    const user = document.getElementById('userSelect').value;
                    const res = await fetch(`/expenses/${user}`);
                    const data = await res.json();
                    console.log("抓取到的歷史紀錄資料:", data);
                    
                    if (!data || data.length === 0) {
                        document.getElementById('historyBody').innerHTML = '<tr><td colspan="4" class="p-4 text-center text-gray-400">尚無歷史紀錄</td></tr>';
                        return;
                    }

                    const body = document.getElementById('historyBody');
                    body.innerHTML = data.map(r => `
                        <tr class="block md:table-row border-b border-slate-50 hover:bg-indigo-50/50 transition-all group mb-4 md:mb-0 p-4 md:p-0 bg-white md:bg-transparent rounded-2xl md:rounded-none shadow-sm md:shadow-none border border-slate-100 md:border-0">
                            <td class="block md:table-cell py-1 md:py-4 text-slate-400 font-medium text-xs md:text-sm">
                                <span class="md:hidden font-bold text-slate-500 mr-2">日期:</span>${r.date}
                            </td>
                            <td class="block md:table-cell py-1 md:py-4 font-black text-slate-700 text-lg md:text-base">
                                <span class="md:hidden font-bold text-slate-500 mr-2">品名:</span>${r.foodname}
                            </td>
                            <td class="block md:table-cell py-1 md:py-4 md:text-right font-black text-indigo-600 text-xl md:text-base">
                                <span class="md:hidden font-bold text-slate-500 mr-2">金額:</span>$${r.amount}
                            </td>
                            <td class="block md:table-cell py-2 md:py-4 md:px-4">
                                <div class="bg-indigo-50 text-indigo-600 p-3 rounded-xl text-xs leading-relaxed italic border border-indigo-100 group-hover:bg-white transition-all">
                                    <span class="md:hidden block font-black not-italic mb-1 text-indigo-400 uppercase text-[10px]">AI 建議</span>
                                    ${r.advice}
                                </div>
                            </td>
                        </tr>
                    `).reverse().join('');
                }

                document.getElementById('userSelect').onchange = () => { loadHistory(); loadBudget(); };
                loadUsers();
            </script>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/users")
def list_users():
    """獲取所有使用者清單"""
    try:
        ws = get_worksheet("User_Data")
        return ws.col_values(2)[1:] # 名稱在第二欄，跳過第一列標題
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/users/{user_name}")
def register_user(user_name: str):
    """註冊新使用者"""
    ws = get_worksheet("User_Data")
    if user_name not in ws.col_values(2):
        ws.append_row(["", user_name]) # 插入資料至第二欄 (第一欄留空)
        return {"status": "success", "message": f"User {user_name} added"}
    return {"status": "exists"}

@app.get("/expenses/{user_name}")
def get_user_expenses(user_name: str):
    """獲取特定使用者的歷史紀錄"""
    ws = get_worksheet("History_record")
    # 取得所有資料，並確保標題列處理正確
    records = ws.get_all_records(head=1)
    if not records:
        return []
        
    df = pd.DataFrame(records)
    # 強制將所有欄位名稱轉為小寫並去除空白，防止 Google Sheet 標題打錯
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    # 中英文欄位映射：確保前端能讀取到正確的 key
    mapping = {
        '日期': 'date',
        '品名': 'foodname',
        '金額': 'amount',
        '建議': 'advice',
        '使用者名稱': 'user_name',
        '分類': 'category',
        '熱量': 'calories',
        '健康評分': 'health_score'
    }
    df.rename(columns=mapping, inplace=True)

    # 偵測欄位是否存在，若不存在則印出目前有的欄位方便除錯
    if 'user_name' not in df.columns:
        print(f"錯誤：工作表缺少 'user_name' 欄位。目前的欄位有: {df.columns.tolist()}")
        return []

    # 過濾資料時也去除內容空白
    user_df = df[df['user_name'].astype(str).str.strip() == user_name.strip()]
    return user_df.to_dict(orient="records")

@app.get("/budget/{user_name}")
def get_budget_status(user_name: str):
    """獲取預算與支出概況"""
    # 1. 計算支出
    expenses = get_user_expenses(user_name)
    now_month = datetime.now().strftime("%Y-%m")
    spent = sum(int(e.get('amount', 0)) for e in expenses if str(e.get('date', '')).startswith(now_month))
    
    # 2. 獲取預算上限
    limit = 15000
    try:
        ws = get_worksheet("Budget")
        records = ws.get_all_records()
        # 從後往前找，取得該使用者最新的預算設定
        for r in reversed(records):
            if str(r.get('user_name', '')).strip() == user_name.strip():
                limit = int(r.get('budget_limit', 15000))
                break
    except: pass # 若無 Budget 表或讀取失敗則維持預設值 15000

    return {"limit": limit, "spent": spent, "remaining": limit - spent}

class BudgetUpdate(BaseModel):
    user_name: str
    budget_limit: int

@app.post("/budget")
def update_budget(data: BudgetUpdate):
    """更新預算設定"""
    ws = get_worksheet("Budget")
    # 如果工作表是空的，先寫入標題以確保功能運作正常
    if not ws.get_all_values():
        ws.append_row(["user_name", "budget_limit"])
    ws.append_row([data.user_name, data.budget_limit])
    return {"status": "success"}

@app.post("/expenses")
def save_expense(item: ExpenseItem):
    """儲存記帳資料"""
    try:
        ws = get_worksheet("History_record")
        # 檢查是否需要寫入標題列（如果工作表是空的）
        if not ws.get_all_values():
            ws.append_row(list(item.dict().keys()))
        
        ws.append_row(list(item.dict().values()))
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze")
async def analyze_transaction(
    text: Optional[str] = Form(None),
    user_name: str = Form(...),
    file: Optional[UploadFile] = File(None)
):
    """AI 辨識端點：支援文字或圖片"""
    # 取得參考資料
    ref_ws = get_worksheet("ref_data")
    ref_data = pd.DataFrame(ref_ws.get_all_records()).to_string(index=False)

    prompt = f"分析食物資料：{text or '請辨識圖片內容'}。參考清單：{ref_data}"
    
    image_content = None
    if file:
        image_content = await file.read()

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[prompt] + ([types.Part.from_bytes(data=image_content, mime_type='image/jpeg')] if image_content else []),
        config={
            "response_mime_type": "application/json",
            "system_instruction": "你是一個飲食記帳專家。請回傳 JSON: {\"date\":\"YYYY-MM-DD\", \"foodname\":\"品名\", \"amount\":金額, \"category\":\"中式/西式/日式/其他\", \"calories\":熱量, \"health_score\":1-10, \"advice\":\"健康建議\"}"
        }
    )
    return json.loads(response.text)

@app.get("/overall-advice/{user_name}")
def get_ai_advice(user_name: str):
    """獲取該使用者的整體 AI 建議"""
    # 獲取歷史紀錄
    expenses = get_user_expenses(user_name)
    if not expenses:
        return {"analysis": {"summary": "尚無資料可分析", "reason": ""}}

    prompt = f"分析以下使用者的歷史飲食與消費紀錄：{json.dumps(expenses)}"
    
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[prompt],
        config={
            "response_mime_type": "application/json",
            "system_instruction": "你是一個結合營養與財務管理的專家。回傳 JSON: {\"analysis\": {\"summary\": \"總結\", \"reason\": \"理由\"}}"
        }
    )
    return json.loads(response.text)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)