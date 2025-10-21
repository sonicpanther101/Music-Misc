import pystray
import requests
from PIL import Image, ImageDraw
import threading
import time
from urllib.parse import urlparse

class SteamMonitor:
    def __init__(self):
        self.status = "unknown"
        self.icon = None
        self.running = True
        
    def create_icon_image(self, color):
        """Create a simple colored circle icon"""
        width = 64
        height = 64
        image = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(image)
        draw.ellipse([8, 8, 56, 56], fill=color, outline='black', width=2)
        return image
    
    def check_steam(self):
        """Check if Steam is accessible and not redirected"""
        try:
            response = requests.get('https://www.instagram.com/', 
                                   timeout=10, 
                                   allow_redirects=True)
            
            # Get the final URL after any redirects
            final_url = response.url
            final_domain = urlparse(final_url).netloc
            
            # Check if we're still on steampowered.com domain
            if 'instagram.com' in final_domain:
                return "online"
            else:
                return "redirected"
        except requests.RequestException:
            return "offline"
    
    def update_status(self):
        """Periodically check Steam status"""
        while self.running:
            print("\rStarting status check...            ", end='', flush=True)
            self.status = self.check_steam()

            print(f"\rSteam status: {self.status}            ", end='', flush=True)
            
            # Update icon based on status
            if self.status == "online":
                color = 'green'
                title = "Steam: Online ✓"
            elif self.status == "redirected":
                color = 'orange'
                title = "Steam: Redirected ⚠"
            else:
                color = 'red'
                title = "Steam: Offline ✗"
            
            if self.icon:
                self.icon.icon = self.create_icon_image(color)
                self.icon.title = title
            
            # Wait 30 seconds before next check
            DURATION = 30
            print()
            for i in range(DURATION):
                print(f"\r{DURATION-i} seconds till next check    ", end='', flush=True)
                time.sleep(1)
    
    def on_quit(self, icon, item):
        """Handle quit action"""
        self.running = False
        icon.stop()
    
    def run(self):
        """Start the system tray icon"""
        # Create initial icon
        image = self.create_icon_image('gray')
        
        # Create menu
        menu = pystray.Menu(
            pystray.MenuItem('Quit', self.on_quit)
        )
        
        # Create icon
        self.icon = pystray.Icon(
            "steam_monitor",
            image,
            "Steam Monitor - Starting...",
            menu
        )
        
        # Start status checking thread
        check_thread = threading.Thread(target=self.update_status, daemon=True)
        check_thread.start()
        
        # Run the icon
        self.icon.run()

if __name__ == "__main__":
    monitor = SteamMonitor()
    monitor.run()