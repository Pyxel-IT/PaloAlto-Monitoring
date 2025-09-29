#!/usr/bin/env python3
"""
Script pour générer une clé API Palo Alto
Usage: python generate_api_key.py <host> <username>
"""

import sys
import getpass
import requests
import urllib3
import xml.etree.ElementTree as ET

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def generate_api_key(host, username, password):
    url = f"https://{host}/api/"
    params = {
        'type': 'keygen',
        'user': username,
        'password': password
    }

    try:
        response = requests.get(url, params=params, verify=False)
        response.raise_for_status()

        root = ET.fromstring(response.text)
        status = root.get('status')

        if status == 'success':
            key = root.find('.//key')
            if key is not None:
                return key.text
            else:
                print("Clé non trouvée dans la réponse")
                return None
        else:
            msg = root.find('.//msg')
            error_msg = msg.text if msg is not None else "Erreur inconnue"
            print(f"Erreur : {error_msg}")
            return None

    except Exception as e:
        print(f"Erreur de connexion : {str(e)}")
        return None


def main():
    if len(sys.argv) != 3:
        print("Usage: python generate_api_key.py <host> <username>")
        sys.exit(1)

    host = sys.argv[1]
    username = sys.argv[2]
    password = getpass.getpass(f"Password for {username}@{host}: ")

    print(f"Génération de la clé API pour {username}@{host}...")
    api_key = generate_api_key(host, username, password)

    if api_key:
        print(f"\nClé API générée avec succès:")
        print(f"{api_key}")
        print("\nAjoutez cette clé dans votre fichier config.yaml")
    else:
        print("Échec de la génération de la clé API")
        sys.exit(1)


if __name__ == "__main__":
    main()