import requests

url = "https://setup.rbxcdn.com/channel/live-eac/version"

response = requests.get(url)
print(response.text)

input("Press Enter to exit...")