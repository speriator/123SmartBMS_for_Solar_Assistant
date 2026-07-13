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

Si vous devez réinstaller ou dupliquer ce projet sur un autre Raspberry Pi à l'avenir, voici les étapes à suivre :

### 1. Activer le SSH sur le nouveau Pi
* Activez l'accès SSH via l'interface web du nouveau Solar-Assistant (onglet **Configuration** > **Configure local access**).
* Identifiez la nouvelle adresse IP du Pi (ex: `192.168.80.XXX`).

### 2. Copier votre clé SSH (depuis ce Mac)
Exécutez depuis votre Mac :
```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub solar-assistant@<NOUVELLE_IP>
```

### 3. Configurer les paramètres matériels (UART / Bluetooth)
Connectez-vous en SSH sur le nouveau Pi, puis :
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

### 4. Transférer les fichiers et installer les services
Une fois le Pi redémarré, exécutez ces commandes depuis votre Mac (dans ce dossier) :
```bash
# 1. Copier le serveur, l'interface web, le script de port virtuel et les fichiers services
scp server_smartbms.py index.html setup_virtual_port.sh smartbms-web.service virtual-bms-port.service solar-assistant@<NOUVELLE_IP>:~/

# 2. Se connecter en SSH pour finaliser
ssh solar-assistant@<NOUVELLE_IP>
```
Puis, sur le shell du nouveau Pi :
```bash
# 3. Installer les dépendances (pyserial et socat)
echo "solar123" | sudo -S apt-get update
echo "solar123" | sudo -S apt-get install -y python3-serial socat

# 4. Enregistrer et activer le service Dashboard Web
sudo mv ~/smartbms-web.service /etc/systemd/system/
sudo chown root:root /etc/systemd/system/smartbms-web.service
sudo systemctl enable smartbms-web.service
sudo systemctl start smartbms-web.service

# 5. Enregistrer et activer le service Port Virtuel (BMS émulé)
sudo mv ~/virtual-bms-port.service /etc/systemd/system/
sudo chown root:root /etc/systemd/system/virtual-bms-port.service
sudo chmod +x ~/setup_virtual_port.sh
sudo mv ~/setup_virtual_port.sh /home/solar-assistant/
sudo systemctl enable virtual-bms-port.service
sudo systemctl start virtual-bms-port.service

# 6. Recharger et redémarrer Solar-Assistant
sudo systemctl daemon-reload
sudo systemctl restart influx-bridge.service
```

---

## Mémoire Technique : Émulation de Port Série pour Solar-Assistant

> [!NOTE]
> **Pourquoi le port `/dev/ttyS9` et le bind mount sysfs sont requis :**
> * **Détection dans Solar-Assistant :** Solar-Assistant utilise la bibliothèque Elixir `Circuits.UART` pour lister les ports. Cette bibliothèque scanne le dossier noyau `/sys/class/tty/`. Un port créé par `socat` (simple lien symbolique) n'y figure pas et n'est donc pas listé dans l'interface web.
> * **Contrainte USB :** Si l'on nomme le port virtuel `ttyUSB9`, le driver de détection s'attend à trouver des descripteurs USB (`idVendor`, `idProduct`) dans `/sys`. En leur absence, le port est écarté.
> * **Solution implémentée :** Le port virtuel a été nommé `/dev/ttyS9` (type plateforme). Le script `setup_virtual_port.sh` effectue un **bind mount** dynamique sur `/sys/class/tty` en y insérant une fausse entrée noyau `ttyS9` clonée sur la configuration du port physique `ttyAMA0` (avec l'attribut `type = 32` qui signale un port actif). Cela force Solar-Assistant à lister le port et permet d'y brancher l'émulateur Daly BMS.

