import streamlit as st
import google.generativeai as genai
from PIL import Image
import os
import json
import requests
import zipfile
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- 設定 ---
PAGE_TITLE = "暗記プリント作成くん Web"
FONT_FILE = "ipaexg.ttf"
FONT_NAME = "IPAexGothic"
# IPA公式サイトのZIPファイルURL
FONT_URL = "https://moji.or.jp/wp-content/ipafont/IPAexfont/ipaexg00401.zip"

def download_font():
    """日本語フォント（IPAexゴシック）を公式からDL・解凍して保存する関数"""
    if not os.path.exists(FONT_FILE):
        st.info("日本語フォントを準備中... (初回のみ10秒ほどかかります)")
        try:
            # 1. 公式サイトからZIPをダウンロード
            response = requests.get(FONT_URL)
            response.raise_for_status()
            
            # 2. メモリ上でZIPを解凍し、ipaexg.ttfだけを取り出す
            with zipfile.ZipFile(BytesIO(response.content)) as z:
                # ZIP内のファイルを探す
                for file_info in z.infolist():
                    if file_info.filename.endswith("ipaexg.ttf"):
                        with open(FONT_FILE, "wb") as f:
                            f.write(z.read(file_info.filename))
                        break
            
            st.success("フォントの準備が完了しました。")
        except Exception as e:
            st.error(f"フォントのダウンロードに失敗しました: {e}")
            return False
    return True

def generate_pdf(qa_data, unit_title, font_path):
    """PDFを生成してバイトデータとして返す関数"""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # フォント登録
    try:
        pdfmetrics.registerFont(TTFont(FONT_NAME, font_path))
        c.setFont(FONT_NAME, 12)
    except Exception as e:
        st.error(f"フォント読み込みエラー: {e}")
        return None

    # レイアウト設定
    margin = 40
    font_size = 10.5
    line_spacing = 15
    padding = 8
    
    printable_width = width - 2 * margin
    q_ratio = 0.7
    divider_x = margin + (printable_width * q_ratio)

    y = height - margin
    
    # タイトル
    c.setFont(FONT_NAME, 16)
    c.drawString(margin, y, unit_title)
    y -= 40
    
    c.setFont(FONT_NAME, font_size)
    c.line(margin, y, width - margin, y)

    for item in qa_data:
        q_text = str(item.get("question", ""))
        a_text = str(item.get("answer", ""))
        
        # 文字数での折り返し
        q_lines = [q_text[i:i+33] for i in range(0, len(q_text), 33)]
        a_lines = [a_text[i:i+13] for i in range(0, len(a_text), 13)]
        
        max_lines = max(len(q_lines), len(a_lines), 1)
        row_height = (max_lines * line_spacing) + (padding * 2)
        
        # 改ページ判定
        if y - row_height < margin:
            c.showPage()
            c.setFont(FONT_NAME, font_size)
            y = height - margin
            c.line(margin, y, width - margin, y)
        
        # 描画
        text_start_y = y - padding - font_size + 2
        
        for i, line in enumerate(q_lines):
            c.drawString(margin + padding, text_start_y - (i * line_spacing), line)
        
        for i, line in enumerate(a_lines):
            c.drawString(divider_x + padding, text_start_y - (i * line_spacing), line)
        
        c.line(divider_x, y, divider_x, y - row_height)
        y -= row_height
        c.line(margin, y, width - margin, y)

    c.save()
    buffer.seek(0)
    return buffer

# --- メイン処理 ---
st.set_page_config(page_title=PAGE_TITLE, layout="wide")
st.title("📱 暗記プリント作成くん Web")

# フォント準備
if not download_font():
    st.stop()

# サイドバー: 設定
with st.sidebar:
    api_key = st.text_input("Gemini API Key", type="password", value="AIzaSyCHYRAUHEUbttuANo9iSWVSoQ1RthSklaQ")
    st.markdown("[APIキーの取得はこちら](https://aistudio.google.com/app/apikey)")
    
    unit_default = "新しい単元"
    unit_name = st.text_input("単元名", value=unit_default)
    num_questions = st.text_input("問題数 (任意)", placeholder="例: 10")
    
    st.markdown("---")
    additional_instructions = st.text_area("AIへの追加指示 (任意)", placeholder="例: 英単語の意味を答える形式にしてください。\n全部ひらがなにしてください。")

# メイン: 画像アップロード
uploaded_files = st.file_uploader("学習プリントの写真をアップロード (複数枚可)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if uploaded_files and api_key:
    # 画像の読み込みと表示
    images = []
    
    # 複数行・列で画像を表示
    cols = st.columns(min(len(uploaded_files), 3))
    for i, file in enumerate(uploaded_files):
        img = Image.open(file)
        images.append(img)
        with cols[i % 3]:
            st.image(img, caption=f"画像 {i+1}", use_container_width=True)

    if st.button("✨ AIで問題を抽出する", type="primary"):
        with st.spinner("AIが考え中... (20秒〜30秒ほどかかります)"):
            try:
                genai.configure(api_key=api_key)
                
                # 利用可能なモデルを動的に取得
                active_model = None
                try:
                    all_models = [m for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                    valid_model_names = [m.name.replace("models/", "") for m in all_models]
                    
                    if valid_model_names:
                        # Flash -> Pro の順で優先順位を決める
                        valid_model_names.sort(key=lambda x: (not "flash" in x, not "1.5" in x))
                        active_model = valid_model_names[0]
                except Exception as e:
                    st.warning(f"モデル一覧の取得に失敗しました: {e}。デフォルト設定で試行します。")
                
                # 取得できなければフォールバック
                if not active_model:
                    active_model = "gemini-1.5-flash"

                model = genai.GenerativeModel(active_model)
                
                count_instruction = ""
                if num_questions and num_questions.isdigit():
                    count_instruction = f"問題数は {num_questions} 問程度作成してください。"
                
                custom_instruction_text = ""
                if additional_instructions:
                    custom_instruction_text = f"【追加の指示】\n{additional_instructions}\nこの指示を最優先して問題作成を行ってください。"

                prompt = f"""
                これらの学習プリントの画像を分析してください。複数枚ある場合は、それらをまとめて一つの単元として扱ってください。
                1. このプリントの「単元名（タイトル）」を推定してください。
                2. 暗記用の一問一答形式の問題と答えを抽出してください。
                {count_instruction}
                {custom_instruction_text}
                
                出力は必ず以下のJSON形式のみにしてください。
                {{
                    "unit_title": "推定された単元名",
                    "qa_list": [
                        {{"question": "問題文...", "answer": "答え..."}}
                    ]
                }}
                テキストが見つからない場合は空のリストを返してください。
                """

                # テキストプロンプトと画像リストを結合して渡す
                content_parts = [prompt] + images
                response = model.generate_content(content_parts)
                text_response = response.text
                
                # --- クリーニング処理 ---
                if "```json" in text_response:
                    text_response = text_response.split("```json")[1].split("```")[0].strip()
                elif "```" in text_response:
                    text_response = text_response.split("```")[1].split("```")[0].strip()
                
                data = json.loads(text_response)
                
                # 結果をSession Stateに保存
                st.session_state["qa_data"] = data.get("qa_list", [])
                st.session_state["unit_title"] = data.get("unit_title", unit_default)
                st.success(f"抽出完了！ ({active_model})")
                
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")

# 結果表示 & 編集エリア
if "qa_data" in st.session_state:
    st.subheader("編集エリア")
    
    if st.session_state.get("unit_title") and unit_name == unit_default:
        unit_name = st.session_state["unit_title"]

    edited_data = st.data_editor(
        st.session_state["qa_data"],
        column_config={
            "question": st.column_config.TextColumn("問題", width="medium"),
            "answer": st.column_config.TextColumn("答え", width="small")
        },
        num_rows="dynamic",
        use_container_width=True
    )
    
    st.divider()
    
    if st.button("📄 PDFを作成する"):
        if not unit_name:
            st.warning("単元名を入力してください")
        else:
            pdf_bytes = generate_pdf(edited_data, unit_name, FONT_FILE)
            if pdf_bytes:
                st.download_button(
                    label="ダウンロード開始",
                    data=pdf_bytes,
                    file_name=f"{unit_name}.pdf",
                    mime="application/pdf"
                )

elif not api_key:
    st.warning("👈 サイドバーでAPIキーを入力してください")

elif not api_key:
    st.warning("👈 サイドバーでAPIキーを入力してください")

