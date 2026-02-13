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
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(FONT_URL, headers=headers)
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

def resize_image(image, max_size=1600):
    """
    画像の長辺がmax_sizeを超えないように、アスペクト比を維持してリサイズする。
    LANCZOSフィルタを使用して、文字の視認性を確保する。
    """
    width, height = image.size
    if max(width, height) > max_size:
        if width > height:
            new_width = max_size
            new_height = int(height * (max_size / width))
        else:
            new_height = max_size
            new_width = int(width * (max_size / height))
        return image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    return image

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
    
    # AIで推定された単元名があればそれを初期値にする
    unit_default = "新しい単元"
    default_unit_val = st.session_state.get("unit_title", unit_default)
    
    unit_name_input = st.text_input("単元名", value=default_unit_val)
    # 入力値を常に最新の状態として保持する（rerun後も反映されるように）
    if unit_name_input != default_unit_val:
        st.session_state["unit_title"] = unit_name_input

    num_questions = st.text_input("問題数 (任意)", placeholder="例: 10")
    
    st.markdown("---")
    additional_instructions = st.text_area("AIへの追加指示 (任意)", placeholder="例: 英単語の意味を答える形式にしてください。\n全部ひらがなにしてください。")


# --- ステート管理による画面切り替え ---

if "qa_data" not in st.session_state:
    # ==========================================================
    # 状態1：初期画面（画像アップロード & 解析）
    # ==========================================================

    uploaded_files = st.file_uploader("学習プリントの写真をアップロード (複数枚可)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

    if uploaded_files and api_key:
        st.markdown(f"**{len(uploaded_files)} 枚の画像を読み込みました**")
        
        # プレビュー表示
        with st.expander("画像のプレビューを表示", expanded=False):
            cols = st.columns(min(len(uploaded_files), 3))
            for i, file in enumerate(uploaded_files):
                img = Image.open(file)
                with cols[i % 3]:
                    st.image(img, caption=f"画像 {i+1}", use_container_width=True)

        if st.button("✨ AIで問題を抽出する (一括処理)", type="primary"):
            # プログレスバーとステータス表示
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            aggregated_qa_list = []
            detected_unit_title = unit_default
            total_files = len(uploaded_files)
            
            genai.configure(api_key=api_key)
            
            # 1. モデル選択ロジック
            valid_model_names = []
            try:
                all_models = [m for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                valid_model_names = [m.name.replace("models/", "") for m in all_models]
                if valid_model_names:
                    # Flash -> Pro の順で優先順位
                    valid_model_names.sort(key=lambda x: (not "flash" in x, not "1.5" in x))
            except Exception as e:
                st.warning(f"モデル一覧の取得に失敗しました: {e}")
            
            if not valid_model_names:
                valid_model_names = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"]

            # 2. プロンプト作成
            count_instruction = ""
            if num_questions and num_questions.isdigit():
                count_instruction = f"全体でバランスよく抽出してください。" 
            
            custom_instruction_text = ""
            if additional_instructions:
                custom_instruction_text = f"【追加の指示】\n{additional_instructions}\nこの指示を最優先して問題作成を行ってください。"

            prompt = f'''
            この学習プリントの画像を分析してください。
            
            【重要ルール】
            1. **画像に書かれている内容のみ**を元に問題を作成してください。
            2. 画像にない知識（外部知識）は絶対に使わないでください。
            3. 「資料を見れば誰でも解ける」レベルの問題に限定してください。
            4. 画像内の説明文や図表から読み取れる事実だけを問いにしてください。

            【タスク】
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
            '''

            try:
                for i, file_obj in enumerate(uploaded_files):
                    current_idx = i + 1
                    status_text.text(f"処理中 ({current_idx}/{total_files}): {file_obj.name} を解析しています...")
                    
                    # 画像を開く & リサイズ (メモリ対策)
                    img = Image.open(file_obj)
                    resized_img = resize_image(img)
                    
                    # Gemini API 呼び出し (リトライループ)
                    response = None
                    last_error = None
                    
                    for model_name in valid_model_names:
                        try:
                            model = genai.GenerativeModel(model_name)
                            response = model.generate_content([prompt, resized_img])
                            break # 成功
                        except Exception as e:
                            last_error = e
                            continue
                    
                    if not response:
                        st.warning(f"{file_obj.name} の解析に失敗しました: {last_error}")
                        continue

                    # JSONパース
                    text_response = response.text
                    if "```json" in text_response:
                        text_response = text_response.split("```json")[1].split("```")[0].strip()
                    elif "```" in text_response:
                        text_response = text_response.split("```")[1].split("```")[0].strip()
                    
                    try:
                        data = json.loads(text_response)
                        page_qa = data.get("qa_list", [])
                        aggregated_qa_list.extend(page_qa)
                        
                        extracted_title = data.get("unit_title", "")
                        if extracted_title and detected_unit_title == unit_default:
                            detected_unit_title = extracted_title
                            
                    except json.JSONDecodeError:
                        st.warning(f"{file_obj.name}: AI応答のパースに失敗しました。")
                        continue
                    
                    progress_bar.progress(current_idx / total_files)

                # ループ終了後
                if aggregated_qa_list:
                    # 結果をSession Stateに保存
                    st.session_state["qa_data"] = aggregated_qa_list
                    st.session_state["unit_title"] = detected_unit_title
                    st.success("抽出完了！画面を切り替えます...")
                    # 画面更新してUploaderを消す
                    st.rerun()
                else:
                    st.warning("問題が見つかりませんでした。")
                    
            except Exception as e:
                st.error(f"システムエラーが発生しました: {e}")

else:
    # ==========================================================
    # 状態2：編集画面（結果確認 & PDFダウンロード）
    # ※ ここでは画像アップローダーを表示しないことでメモリを節約する
    # ==========================================================
    
    st.info("✅ 抽出が完了しました。以下の表で内容を編集し、PDFを作成してください。")

    # リセットボタン（最初に戻る）
    if st.button("🔄 別の画像を処理する（リセット）"):
        del st.session_state["qa_data"]
        if "unit_title" in st.session_state:
            del st.session_state["unit_title"]
        st.rerun()

    st.divider()
