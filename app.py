import streamlit as st
import google.generativeai as genai
from PIL import Image
import os
import json
import requests
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- 設定 ---
PAGE_TITLE = "暗記プリント作成くん Web"
# Google Fontsの安定したURLを使用 (Noto Sans JP Regular)
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP-Regular.ttf"
FONT_FILE = "NotoSansJP-Regular.ttf"
FONT_NAME = "NotoSansJP"

def download_font():
    """日本語フォントをダウンロードして保存する関数"""
    if not os.path.exists(FONT_FILE):
        st.info("フォントを準備中... (初回のみ)")
        try:
            response = requests.get(FONT_URL)
            response.raise_for_status()
            with open(FONT_FILE, "wb") as f:
                f.write(response.content)
            st.success("フォント準備完了！")
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
    api_key = st.text_input("Gemini API Key", type="password")
    st.markdown("[APIキーの取得はこちら](https://aistudio.google.com/app/apikey)")
    
    unit_default = "新しい単元"
    unit_name = st.text_input("単元名", value=unit_default)
    num_questions = st.text_input("問題数 (任意)", placeholder="例: 10")

# メイン: 画像アップロード
uploaded_file = st.file_uploader("学習プリントの写真をアップロード", type=["jpg", "jpeg", "png"])

if uploaded_file and api_key:
    image = Image.open(uploaded_file)
    st.image(image, caption="アップロード画像", use_column_width=True)
    
    if st.button("✨ AIで問題を抽出する", type="primary"):
        with st.spinner("AIが考え中... (20秒〜30秒ほどかかります)"):
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                
                count_instruction = ""
                if num_questions and num_questions.isdigit():
                    count_instruction = f"問題数は {num_questions} 問程度作成してください。"

                prompt = f"""
                この学習プリントの画像を分析してください。
                1. このプリントの「単元名（タイトル）」を推定してください。
                2. 暗記用の一問一答形式の問題と答えを抽出してください。
                {count_instruction}
                
                出力は必ず以下のJSON形式のみにしてください。
                {{
                    "unit_title": "推定された単元名",
                    "qa_list": [
                        {{"question": "問題文...", "answer": "答え..."}}
                    ]
                }}
                テキストが見つからない場合は空のリストを返してください。
                """
                
                response = model.generate_content([prompt, image])
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
                st.success("抽出完了！")
                
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
