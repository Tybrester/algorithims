#!/usr/bin/env python3
"""
Deployment script for Namecheap SFTP hosting
Uploads frontend files to Namecheap hosting via SFTP
"""

import os
import sys
import paramiko

# Configuration - update these with your Namecheap SFTP credentials
SFTP_HOST = "your-server-hostname.com"  # Your server hostname or IP
SFTP_USER = "your-cpanel-username"      # Your cPanel username
SFTP_PASS = "your-cpanel-password"      # Your cPanel password
SFTP_PORT = 21098                       # SFTP port for Namecheap
SFTP_DIR = "/public_html"               # Usually public_html for main domain

# Files to deploy
FILES_TO_DEPLOY = [
    "bots.html",
    "index.html",
    "dashboard.html",
    "signin.html",
    "admin.html",
]

def deploy():
    """Deploy files to Namecheap via SFTP"""
    
    # Check if files exist locally
    missing_files = [f for f in FILES_TO_DEPLOY if not os.path.exists(f)]
    if missing_files:
        print(f"Error: Missing files: {missing_files}")
        sys.exit(1)
    
    try:
        print(f"Connecting to SFTP: {SFTP_HOST}:{SFTP_PORT}")
        
        # Create SSH client
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(SFTP_HOST, port=SFTP_PORT, username=SFTP_USER, password=SFTP_PASS)
        
        # Create SFTP client
        sftp = ssh.open_sftp()
        print("Connected successfully")
        
        # Change to target directory
        sftp.chdir(SFTP_DIR)
        print(f"Changed to directory: {SFTP_DIR}")
        
        # Upload each file
        for filename in FILES_TO_DEPLOY:
            print(f"Uploading {filename}...")
            sftp.put(filename, filename)
            print(f"✓ {filename} uploaded")
        
        sftp.close()
        ssh.close()
        print("\n✓ Deployment complete!")
        
    except Exception as e:
        print(f"Error during deployment: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=== Namecheap SFTP Deployment Script ===")
    print("Make sure to update SFTP credentials in deploy.py before running")
    print()
    
    # Check if credentials are still default
    if SFTP_HOST == "your-server-hostname.com":
        print("⚠️  Please update SFTP credentials in deploy.py first:")
        print("   - SFTP_HOST (your server hostname)")
        print("   - SFTP_USER (your cPanel username)")
        print("   - SFTP_PASS (your cPanel password)")
        print("   - SFTP_PORT (usually 21098 for Namecheap)")
        sys.exit(1)
    
    # Check if paramiko is installed
    try:
        import paramiko
    except ImportError:
        print("⚠️  Installing required package: paramiko")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
        print("✓ paramiko installed")
    
    deploy()
