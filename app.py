import os
import shutil
import subprocess
import threading
import signal
from flask import Flask, request, send_from_directory, render_template_string, redirect, url_for

app = Flask(__name__)

# ---------------- НАСТРОЙКИ ----------------
WORK_DIR = r"E:\vpn_site\work"
OLD_DIR = os.path.join(WORK_DIR, "old")
EXE_PATH = os.path.join(WORK_DIR, "Elib2EbookCli.exe")
PASSWORD = "T2_FF"

if not os.path.exists(OLD_DIR):
    os.makedirs(OLD_DIR)

# ---------------- СОСТОЯНИЕ ----------------
job_running = False
console_output = []
error_message = None
current_process = None  # Для хранения ссылки на процесс

# ---------------- HTML ----------------
HTML = """
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>VPN Parser</title>
<style>
    body { font-family: sans-serif; margin: 20px; background: #f4f4f4; }
    .container { max-width: 800px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
    .console { background:#111; color:#0f0; padding:10px; max-height:400px; overflow:auto; font-family: monospace; font-size: 12px; border-radius: 5px; }
    .error { color: red; font-weight: bold; border: 1px solid red; padding: 10px; margin-bottom: 10px; }
    .status-box { padding: 15px; border-radius: 5px; margin: 10px 0; }
    .running { background: #e3f2fd; border-left: 5px solid #2196f3; }
    .ready { background: #e8f5e9; border-left: 5px solid #4caf50; }
    button { padding: 10px 20px; cursor: pointer; }
    .btn-del { background:#ffcdd2; border:1px solid #ef9a9a; margin-left: 10px; }
    .btn-stop { background:#ff5252; color: white; border:none; margin-top: 10px; }
    .btn-archive { background:#fff176; border:1px solid #fbc02d; margin-left: 10px; }
</style>

<script>
function confirmDelete() {
    let pwd = prompt("Введите пароль для удаления файла:");
    if (pwd === null) return;
    window.location.href = "/delete?password=" + encodeURIComponent(pwd);
}
</script>

</head>
<body>
<div class="container">
    <h3>Создание задачи</h3>

    {% if error %}
        <div class="error">{{ error }}</div>
    {% endif %}

    <form method="post" action="/">
      Ссылка:<br>
      <input name="url" style="width:100%; box-sizing: border-box; padding: 8px;" required {% if job_running %}disabled{% endif %}><br><br>
      Пароль:<br>
      <input name="password" type="password" style="width:100%; box-sizing: border-box; padding: 8px;" required {% if job_running %}disabled{% endif %}><br><br>
      <button type="submit" {% if job_running %}disabled{% endif %}>
        {% if job_running %}Скачивается...{% else %}Запустить{% endif %}
      </button>
    </form>

    <hr>

    {% if job_running %}
        <div class="status-box running">
            <h3 style="margin:0; color: #0d47a1;">⏳ Статус: Идет скачивание...</h3>
            <p>Страница обновится автоматически.</p>
            <a href="/stop"><button class="btn-stop">ОСТАНОВИТЬ</button></a>
        </div>
        <script>setTimeout(() => { if(!window.location.search.includes('stop')) location.href='/'; }, 2000);</script>
    {% elif file %}
        <div class="status-box ready">
            <h3 style="margin:0; color: #1b5e20;">✅ Файл готов: {{ file }}</h3><br>
            <a href="/download"><button>Скачать файл</button></a>
            <a href="/archive"><button class="btn-archive">В архив</button></a>
            <button class="btn-del" onclick="confirmDelete()">Удалить</button>
        </div>
    {% else %}
        <h3>Статус: Ожидание новой ссылки</h3>
    {% endif %}

    {% if log %}
    <h4>Логи консоли:</h4>
    <pre class="console">{{ log }}</pre>
    {% endif %}
</div>
</body>
</html>
"""

# ---------------- ЛОГИКА ----------------

def find_fb2():
    if not os.path.exists(WORK_DIR): return None
    for f in os.listdir(WORK_DIR):
        if f.lower().endswith(".fb2") and os.path.isfile(os.path.join(WORK_DIR, f)):
            return f
    return None

def move_to_old():
    f = find_fb2()
    if f:
        src = os.path.join(WORK_DIR, f)
        dst = os.path.join(OLD_DIR, f)
        if os.path.exists(dst): os.remove(dst)
        shutil.move(src, dst)

def run_process(url):
    global job_running, console_output, current_process
    try:
        current_process = subprocess.Popen(
            [EXE_PATH, "-u", url, "-f", "fb2", "-t", "10"],
            cwd=WORK_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        for line in current_process.stdout:
            console_output.append(line.rstrip())
        current_process.wait()
    except Exception as e:
        console_output.append(f"Ошибка: {str(e)}")
    finally:
        job_running = False
        current_process = None

@app.route("/", methods=["GET", "POST"])
def index():
    global job_running, console_output, error_message

    if request.method == "POST":
        if job_running: return redirect(url_for('index'))
        
        pwd = request.form.get("password")
        url = request.form.get("url", "").strip()

        if pwd != PASSWORD:
            error_message = "Неверный пароль!"
            return redirect(url_for('index'))

        error_message = None
        move_to_old()
        console_output = []
        job_running = True
        threading.Thread(target=run_process, args=(url,), daemon=True).start()
        return redirect(url_for('index'))

    curr_error = error_message
    error_message = None
    return render_template_string(
        HTML,
        job_running=job_running,
        log="\n".join(console_output[-100:]),
        file=find_fb2(),
        error=curr_error
    )

@app.route("/stop")
def stop():
    global job_running, current_process, console_output
    if current_process:
        try:
            current_process.terminate() # Мягкая остановка
            current_process.kill()      # Жесткая остановка
        except: pass
    
    # Удаляем файл, если он успел создаться (т.к. скачивание прервано)
    f = find_fb2()
    if f:
        try: os.remove(os.path.join(WORK_DIR, f))
        except: pass
        
    job_running = False
    console_output.append("--- ПРОЦЕСС ОСТАНОВЛЕН ПОЛЬЗОВАТЕЛЕМ ---")
    return redirect(url_for('index'))

@app.route("/archive")
def archive():
    move_to_old()
    return redirect(url_for('index'))

@app.route("/download")
def download():
    f = find_fb2()
    if not f: return "Файл не найден", 404
    return send_from_directory(WORK_DIR, f, as_attachment=True)

@app.route("/delete")
def delete():
    global error_message
    client_pwd = request.args.get("password")
    
    if client_pwd == PASSWORD:
        f = find_fb2()
        if f:
            try: os.remove(os.path.join(WORK_DIR, f))
            except: pass
    else:
        error_message = "Удаление отменено: неверный пароль."
        
    return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
