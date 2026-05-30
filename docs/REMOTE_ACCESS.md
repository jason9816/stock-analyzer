# 手機遠端開發存取（SSH 金鑰 + TOTP 2FA）

從手機連回這台機器做開發。安全模型：**SSH 金鑰（你有的）+ 認證 app 動態碼（你知道的）= 雙因子**。
登入要同時通過金鑰與 6 位數 TOTP，光偷到其中一個沒用。

> 這些是系統/帳號設定，請你自己在終端機執行（含 `sudo`）。可在本對話用 `! <指令>` 直接跑，
> 輸出會回到這裡。**不要把私鑰或 `.env` commit 進 git。**

---

## 1. 產生手機專用金鑰（在這台機器）

```bash
ssh-keygen -t ed25519 -f ~/.ssh/phone_dev_ed25519 -C "phone-dev"
cat ~/.ssh/phone_dev_ed25519.pub >> ~/.ssh/authorized_keys
chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys
```

把**私鑰** `~/.ssh/phone_dev_ed25519` 安全傳到手機後（見步驟 4），**從機器刪掉**：
```bash
shred -u ~/.ssh/phone_dev_ed25519     # 確認手機已匯入再刪
```
（更安全的替代：直接在手機 app 產生金鑰、只把它的「公鑰」貼進上面的 `authorized_keys`，私鑰永不離開手機。）

---

## 2. 裝 TOTP（google-authenticator）並掃 QR

```bash
sudo apt update && sudo apt install -y libpam-google-authenticator
google-authenticator
```
互動問題建議：時間型 token (y)、更新檔案 (y)、禁止重用 (y)、開啟速率限制 (y)。
畫面會印出 **QR code** → 用手機認證 app（Google Authenticator / Authy / 1Password）掃描。
**抄下備援碼**收好（手機遺失時用）。

---

## 3. 設 sshd 要求「金鑰 + TOTP」雙因子

編輯 `/etc/ssh/sshd_config`（`sudo nano /etc/ssh/sshd_config`），確保：
```
KbdInteractiveAuthentication yes
AuthenticationMethods publickey,keyboard-interactive
PasswordAuthentication no
```
編輯 `/etc/pam.d/sshd`：把 `@include common-auth` 註解掉（避免又問密碼），加一行：
```
auth required pam_google_authenticator.so
```
重啟：
```bash
sudo systemctl restart ssh    # 或 sshd
```
> ⚠️ 重啟前**保留一個現有 SSH 連線**測試，鎖死自己時還能救。

---

## 4. 手機端設定

1. 裝 SSH app：iOS → **Termius** 或 **Blink Shell**；Android → **Termius** 或 **JuiceSSH**。
2. 匯入步驟 1 的**私鑰** `phone_dev_ed25519`（用 AirDrop / 加密傳輸；匯入後刪掉傳輸檔）。
3. 新增主機：Host = 機器 IP、Port = 22、User = 你的帳號、Key = 剛匯入的私鑰。
4. 連線時：金鑰自動驗證 → 再輸入認證 app 的 6 位數碼。
5. 進去後用 `tmux`（`tmux new -s dev` / `tmux attach -t dev`），斷線也不中斷開發。

---

## 5. 不想開公網 port？用 Tailscale（建議）

公網直開 22 port 會被掃。用 Tailscale 組私有網路，手機只能透過你的 Tailscale 帳號連回來（帳號本身可再開 2FA）：

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```
手機裝 Tailscale app 並登入同帳號 → SSH 連 Tailscale 給的 100.x 內網 IP。
這樣「Tailscale 帳號 + SSH 金鑰 + TOTP」三層，且不暴露在公網。

---

## 安全提醒
- `.env`（Telegram / Alpaca / Gemini 金鑰）在這台機器上——遠端被入侵等於這些外洩，所以才用雙因子。
- 私鑰只放手機，機器端只留公鑰。
- 定期看 `~/.ssh/authorized_keys`，移除不認得的金鑰。
