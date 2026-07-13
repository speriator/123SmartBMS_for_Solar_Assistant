# Mémoire de Configuration - Solar-Assistant

Ce document regroupe les informations de connexion et de configuration pour Solar-Assistant installé sur le Raspberry Pi 3.

## Informations Réseau
- **Adresse IP locale :** `192.168.80.186`
- **Interface Web :** [http://192.168.80.186](http://192.168.80.186)

## Accès SSH
Pour vous connecter en ligne de commande depuis votre macOS :
- **Utilisateur :** `solar-assistant`
- **Mot de passe (par défaut) :** `solar123`
- **Configuration Clé SSH :** Activée et configurée (connexion sans mot de passe depuis ce Mac)
- **Commande de connexion :**
  ```bash
  ssh solar-assistant@192.168.80.186
  ```

---
> [!NOTE]
> Le statut "Local password : Default" signifie que le mot de passe local d'usine par défaut (`solar123`) est actif. Il est recommandé de le modifier dans l'interface web sous **Configuration** > **Local access** pour sécuriser votre installation.

---

## Procédure de Duplication sur un nouveau Raspberry Pi

Si vous devez réinstaller ou dupliquer ce projet sur un autre Raspberry Pi à l'avenir, voici les étapes à suivre depuis le Terminal de votre Mac (en vous plaçant dans ce dossier de projet) :

### 1. Activer le SSH sur le nouveau Pi
* Activez l'accès SSH via l'interface web du nouveau Solar-Assistant (onglet **Configuration** > **Configure local access**).
* Identifiez la nouvelle adresse IP du Pi (ex: `192.168.80.XXX`).

### 2. Copier votre clé SSH (pour l'accès sans mot de passe)
Exécutez depuis votre Mac :
```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub solar-assistant@<NOUVELLE_IP>
```

### 3. Configurer les paramètres matériels (UART / Bluetooth)
Connectez-vous en SSH sur le nouveau Pi, ou lancez un script pour effectuer ces modifications système :
* Retirez la portion `console=serial0,115200` du fichier `/boot/firmware/cmdline.txt`.
* Ajoutez ces deux lignes à la fin de `/boot/firmware/config.txt` :
  ```text
  enable_uart=1
  dtoverlay=disable-bt
  ```
* Désactivez le service Bluetooth et redémarrez le Pi :
  ```bash
  sudo systemctl disable hciuart
  sudo reboot
  ```

### 4. Transférer les fichiers et lancer le service web
Une fois le Pi redémarré, exécutez ces commandes depuis votre Mac (dans ce dossier) :
```bash
# 1. Copier le serveur, l'interface web et le fichier service
scp server_smartbms.py index.html smartbms-web.service solar-assistant@<NOUVELLE_IP>:~/

# 2. Se connecter en SSH pour finaliser
ssh solar-assistant@<NOUVELLE_IP>
```
Puis, une fois connecté sur le shell du nouveau Pi :
```bash
# 3. Installer pyserial
sudo apt-get update && sudo apt-get install -y python3-serial

# 4. Enregistrer le service systemd
sudo mv ~/smartbms-web.service /etc/systemd/system/
sudo chown root:root /etc/systemd/system/smartbms-web.service

# 5. Activer et démarrer l'application
sudo systemctl daemon-reload
sudo systemctl enable smartbms-web.service
sudo systemctl start smartbms-web.service
```
L'interface web sera immédiatement disponible à l'adresse : `http://<NOUVELLE_IP>:8080`.
