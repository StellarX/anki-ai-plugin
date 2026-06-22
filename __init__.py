# -*- coding: utf-8 -*-
import json
import time
import urllib.error
import urllib.request

from aqt import mw
from aqt.qt import *
from aqt.utils import showInfo

# 尝试导入 markdown 库
try:
    import markdown

    HAS_MARKDOWN = True
except ImportError:
    markdown = None
    HAS_MARKDOWN = False

# ================= 配置读取逻辑 =================
config = mw.addonManager.getConfig(__name__)
API_KEY = config.get('api_key', '').strip()
MODEL_NAME = config.get('model', 'glm-4-flash')
API_URL = config.get('api_url', 'https://open.bigmodel.cn/api/paas/v4/chat/completions')


# ===============================================

class AIQueryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 助手 (Enter发送 / Ctrl+Enter换行)")
        self.resize(600, 500)
        # 支持最大化 / 最小化按钮（可放大展示）
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMinMaxButtonsHint
        )

        # 整体深色背景
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                font-size: 14px;
            }
            QLabel {
                color: #bbbbbb;
            }
            QTextEdit, QTextBrowser {
                background-color: #2d2d2d;
                color: #d4d4d4;
                border: none;
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #4e4e4e;
            }
            QPushButton:pressed {
                background-color: #5a5a5a;
            }
        """)

        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)

        # 布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 结果显示区域
        self.output_area = QTextBrowser()
        self.output_area.setReadOnly(True)
        self.output_area.setOpenExternalLinks(True)
        self.output_area.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | 
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.output_area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # 不再需要 anchorClicked 信号，已删除复制功能
        layout.addWidget(self.output_area, stretch=1)

        # 输入区域
        input_label = QLabel("输入框 (Enter发送 / Ctrl+Enter换行):")
        layout.addWidget(input_label)

        self.input_area = QTextEdit()
        self.input_area.setPlaceholderText("请输入问题...")
        self.input_area.setFixedHeight(80)
        layout.addWidget(self.input_area)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self.on_send)

        self.clear_btn = QPushButton("新对话")
        self.clear_btn.clicked.connect(self.on_clear)

        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.send_btn)
        layout.addLayout(btn_layout)

        # 上下文历史
        self.history = []

        # 初始不显示任何欢迎文字，纯净界面
        self.output_area.setHtml("")
        self.input_area.setFocus()

    def _format_message(self, role, content):
        """格式化消息，支持 Markdown 渲染"""

        if role == "user":
            # 用户消息：左侧蓝灰气泡
            content_escaped = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            content_formatted = content_escaped.replace('\n', '<br>')

            return f"""
            <div style='margin: 8px 0;'>
              <div style='text-align: left;'>
                <span style='color: #d4d4d4; padding: 6px 10px; border-radius: 8px; display: inline-block; max-width: 85%; word-wrap: break-word;'>
                  <b>用户:</b><br><br>{content_formatted}<br><br>
                </span>
              </div>
            </div>
            """
        else:
            # AI 消息：右侧绿色气泡 + Markdown 渲染
            if HAS_MARKDOWN:
                html_content = markdown.markdown(
                    content,
                    extensions=['markdown.extensions.fenced_code', 'markdown.extensions.tables']
                )
            else:
                html_content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n',
                                                                                                               '<br>')

            # 代码块样式
            html_content = html_content.replace(
                '<pre>',
                '<pre style="background-color: #3c3c3c; padding: 8px; border-radius: 4px; white-space: pre-wrap; margin: 5px 0;">'
            )
            html_content = html_content.replace(
                '<code>',
                '<code style="background-color: #3c3c3c; padding: 2px 4px; border-radius: 3px;">'
            )
            html_content = html_content.replace(
                '<blockquote>',
                '<blockquote style="border-left: 4px solid #555; margin: 5px 0; padding-left: 10px; color: #aaa;">'
            )

            return f"""
            <div style='margin: 8px 0;'>
              <div style='text-align: left;'>
                <span style='color: #d4d4d4; padding: 6px 10px; border-radius: 8px; display: inline-block; max-width: 85%; word-wrap: break-word;'>
                  <b>笨蛋:</b>{html_content}<br>
                </span>
              </div>
            </div>
            """

    def on_clear(self):
        self.history = []
        self.output_area.setHtml("")

    def on_send(self):
        query = self.input_area.toPlainText().strip()
        if not query:
            return

        self._append_message("user", query)
        self.input_area.setPlainText("")
        self.send_btn.setEnabled(False)
        self.send_btn.setText("回答中...")

        self.history.append({"role": "user", "content": query})
        mw.taskman.run_in_background(self.query_ai, lambda future: self.on_response(future.result()))

    def query_ai(self):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        }
        payload = {
            "model": MODEL_NAME,
            "messages": self.history
        }

        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(API_URL, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                content = result['choices'][0]['message']['content']
                return ("success", content)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ""
            return ("error", f"请求错误: {e.code} {e.reason}\n{error_body}")
        except Exception as e:
            return ("error", f"发生错误: {str(e)}")

    def on_response(self, result):
        status, response_text = result

        if status == "error":
            error_html = f"""
            <div style='margin: 8px 0; text-align: center;'>
              <span style='background-color: #5a1d1d; color: #ffcccc; padding: 6px 10px; border-radius: 8px; display: inline-block;'>
                ⚠️ {response_text}
              </span>
            </div>
            """
            self._append_html(error_html)
        else:
            self.history.append({"role": "assistant", "content": response_text})
            self._append_message("assistant", response_text)

        self.send_btn.setEnabled(True)
        self.send_btn.setText("发送")

    def _append_message(self, role, content):
        html = self._format_message(role, content)
        self._append_html(html)

    def _append_html(self, html):
        cursor = self.output_area.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertHtml(html)

        scrollbar = self.output_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


# ================= 输入框事件过滤器 =================
class InputFilter(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.dialog.on_send()
                return True
            elif event.key() == Qt.Key.Key_Return and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                cursor = self.dialog.input_area.textCursor()
                cursor.insertText("\n")
                return True
        return False


# ================= 热键监听逻辑 =================
class TripleCtrlListener(QObject):
    def __init__(self):
        super().__init__(parent=mw)
        self.last_press_time = 0
        self.press_count = 0
        self.dlg = None
        self.input_filter = None
        mw.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Control and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier or
                                                          event.modifiers() & Qt.KeyboardModifier.AltModifier):

                current_time = time.time()

                if current_time - self.last_press_time < 0.4:
                    self.press_count += 1
                else:
                    self.press_count = 1

                self.last_press_time = current_time

                if self.press_count == 3:
                    self.press_count = 0
                    self.show_dialog()
                    return True

        return False

    def show_dialog(self):
        if self.dlg is None:
            self.dlg = AIQueryDialog(mw)
            self.input_filter = InputFilter(self.dlg)
            self.dlg.input_area.installEventFilter(self.input_filter)

        self.dlg.show()
        self.dlg.activateWindow()
        self.dlg.input_area.setFocus()
        scrollbar = self.dlg.output_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


# 初始化插件
if not API_KEY:
    showInfo("插件提示：请在 Anki -> 工具 -> 插件 -> anki-plugin -> 配置 中设置 API Key 后重启Anki")
else:
    listener = TripleCtrlListener()
