# 🤖 Telegram Attendance Bot (Python + Railway)

यह Python Bot आपके n8n workflow के सभी फीचर्स को 100% सटीक तरीके से Python में रिप्लेस करता है।

---

## ⚡ Features (Features Overview)

1. **⏰ Morning Announcement (06:00 AM IST)**
   - हर सुबह 6:00 बजे Telegram Group में Attendance Open होने का Notification भेजता है।

2. **📝 Attendance & Leave Handling (06:00 AM – 10:00 AM IST)**
   - `/present` या `/leave [Reason]` कमांड्स को सिर्फ ग्रुप में 6 AM से 10 AM के बीच प्रोसेस करता है।
   - Duplicate Entry रोकता है ("Already Marked" मैसेज और User कमांड को Auto-Delete करता है)।
   - Streak Track करता है (`🔥 X-Day Streak! [Badge]`) और badges assign करता है:
     - 👑 `[Legend]` (30+ Days)
     - 🌟 `[Gold]` (15+ Days)
     - 🔥 `[Silver]` (7+ Days)
     - ⚡ `[Rising Star]` (3+ Days)
   - Attendance Logs को Google Sheets (`Admissions` sheet) में Save करता है।

3. **📊 Personal Status (`/mystatus`)**
   - User को उसकी Total Logs, Present Days, Leave Days, Attendance Rate % और Current Streak कार्ड भेजता है।
   - 60 सेकेंड बाद कार्ड को खुद Auto-Delete कर देता है।

4. **📄 Admission Form (`/admissionform`)**
   - Admission Form Link तुरंत सेंड करता है।

5. **🌙 9 PM Daily Attendance Report (21:00 PM IST)**
   - Google Sheets (`Members` & `Admissions` sheets) से डेटा रीड करके Complete Summary (Present, Leave, Absent & 3+ Days Consecutive Absentees) तैयार करता है और Telegram Group में पोस्ट करता है।

---

## 🚀 Railway पर Free Deploy करने का Step-by-Step तरीका

### STEP 1: Google Service Account Credentials प्राप्त करें
1. [Google Cloud Console](https://console.cloud.google.com/) में जाएँ और नया Project बनाएँ।
2. **APIs & Services** में जा कर `Google Sheets API` और `Google Drive API` Enable करें।
3. **Credentials** > **Create Credentials** > **Service Account** पर क्लिक करें।
4. Service Account बनने के बाद, उस पर क्लिक करके **Keys** tab में जाएँ और **Add Key > Create New Key (JSON)** चुनें।
5. JSON फाइल आपके कंप्यूटर में डाउनलोड होगी। उस JSON की पूरी Text (Content) को कॉपी कर लें।
6. **IMPORTANT:** डाउनलोड हुई JSON फाइल में एक `client_email` होगी (e.g. `your-bot@project.iam.gserviceaccount.com`)। अपनी Google Sheet (`123XUsCdQRMTt_HtcHclEE8RRoFYoAl27KDBi1Ealn3E`) खोलें और इस `client_email` को **Editor Access** देकर Share कर दें।

---

### STEP 2: GitHub Repository में Code Push करें
1. GitHub पर एक नई **Private / Public Repository** बनाएँ (e.g. `telegram-attendance-bot`)।
2. इस फोल्डर की सभी फाइलों को अपने GitHub Repo पर पुश (Push) कर दें:
```bash
git init
git add .
git commit -m "Initial Attendance Bot Commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/telegram-attendance-bot.git
git push -u origin main
```

---

### STEP 3: Railway.app पर Host करें
1. [Railway.app](https://railway.app/) पर लॉग इन करें (GitHub से Connect करें)।
2. **New Project** > **Deploy from GitHub repo** चुनें।
3. अपनी Repository `telegram-attendance-bot` को सेलेक्ट करें।
4. **Variables** (Environment Variables) tab में जाकर निम्नलिखित Keys जोड़ें:

| Key | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | `8974478810:AAEgxD-ikJrMwV_JSBJY9F45ppBhefoZjtg` |
| `TELEGRAM_CHAT_ID` | `-1003493006883` |
| `GOOGLE_SHEET_ID` | `123XUsCdQRMTt_HtcHclEE8RRoFYoAl27KDBi1Ealn3E` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | *(Google Cloud से डाउनलोड किए गए Service Account JSON का पूरा raw code)* |

5. Railway automatic build करके bot को स्टार्ट कर देगा! logs चेक करें कि `Bot started successfully in polling mode...` दिखाई दे रहा है या नहीं।

---

## 💻 Local test करने के लिए:
```bash
pip install -r requirements.txt
python bot.py
```
