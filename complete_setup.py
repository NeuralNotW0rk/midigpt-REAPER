"""
Complete setup script with fixed Windows copying.
"""

import os
import sys
import shutil
import platform
from pathlib import Path
import subprocess


def setup_reaper_integration():
    """Setup REAPER integration by copying files to REAPER directories."""
    
    # Determine REAPER path based on OS
    if platform.system() == "Darwin":
        reaper_path = Path.home() / "Library/Application Support/REAPER"
    elif platform.system() == "Windows":
        reaper_path = Path.home() / "AppData/Roaming/REAPER"
    else:
        reaper_path = Path.home() / ".config/REAPER"
    
    if not reaper_path.exists():
        print(f"REAPER not found at {reaper_path}")
        print("Please install REAPER first")
        return False
    
    print(f"Setting up REAPER integration at: {reaper_path}")
    print()
    
    project_root = Path.cwd()
    scripts_src = project_root / "src" / "Scripts" / "composers_assistant_v2"
    effects_src = project_root / "src" / "Effects" / "composers_assistant_v2"
    
    scripts_dst = reaper_path / "Scripts" / "composers_assistant_v2"
    effects_dst = reaper_path / "Effects" / "composers_assistant_v2"
    
    success = True
    
    # Handle Scripts
    if scripts_src.exists():
        print(f"Processing Scripts...")
        print(f"  Source: {scripts_src}")
        print(f"  Destination: {scripts_dst}")
        
        try:
            # Remove existing destination (whether symlink or directory)
            if scripts_dst.exists() or scripts_dst.is_symlink():
                if scripts_dst.is_symlink():
                    scripts_dst.unlink()
                    print(f"  Removed existing symlink")
                elif scripts_dst.is_dir():
                    shutil.rmtree(scripts_dst)
                    print(f"  Removed existing directory")
            
            # Create parent directory
            scripts_dst.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy all files
            shutil.copytree(scripts_src, scripts_dst, dirs_exist_ok=True)
            print(f"  [OK] Scripts copied successfully")
            
            # Verify key files
            key_files = ['rpr_mmm_functions.py', 'mmm_nn_server.py']
            for fname in key_files:
                if (scripts_dst / fname).exists():
                    print(f"    - {fname} ✓")
                else:
                    print(f"    - {fname} ✗ MISSING")
                    success = False
            
        except Exception as e:
            print(f"  [ERROR] Failed to copy Scripts: {e}")
            import traceback
            traceback.print_exc()
            success = False
    else:
        print(f"  [WARNING] Source not found: {scripts_src}")
        success = False
    
    print()
    
    # Handle Effects
    if effects_src.exists():
        print(f"Processing Effects...")
        print(f"  Source: {effects_src}")
        print(f"  Destination: {effects_dst}")
        
        try:
            # Remove existing destination (whether symlink or directory)
            if effects_dst.exists() or effects_dst.is_symlink():
                if effects_dst.is_symlink():
                    effects_dst.unlink()
                    print(f"  Removed existing symlink")
                elif effects_dst.is_dir():
                    shutil.rmtree(effects_dst)
                    print(f"  Removed existing directory")
            
            # Create parent directory
            effects_dst.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy all files
            shutil.copytree(effects_src, effects_dst, dirs_exist_ok=True)
            print(f"  [OK] Effects copied successfully")
            
            # Verify key files
            key_files = ['MMM Track Options.js', 'MMM Global Options']
            for fname in key_files:
                if (effects_dst / fname).exists():
                    print(f"    - {fname} ✓")
                else:
                    print(f"    - {fname} ✗ MISSING")
                    success = False
            
        except Exception as e:
            print(f"  [ERROR] Failed to copy Effects: {e}")
            import traceback
            traceback.print_exc()
            success = False
    else:
        print(f"  [WARNING] Source not found: {effects_src}")
        success = False
    
    print()
    
    if success:
        print("="*60)
        print("REAPER INTEGRATION SETUP COMPLETE")
        print("="*60)
        print()
        print("Files copied to:")
        print(f"  {scripts_dst}")
        print(f"  {effects_dst}")
        print()
        print("Next steps:")
        print("  1. Restart REAPER")
        print("  2. In REAPER, add 'MMM Global Options' to Monitor FX")
        print("  3. Add 'MMM Track Options' to tracks as needed")
        print("  4. Start mmm_nn_server.py before running scripts")
        print()
        print("Note: Files are copied, not symlinked.")
        print("      Run this script again to update after code changes.")
    else:
        print("="*60)
        print("SETUP INCOMPLETE - SOME FILES MISSING")
        print("="*60)
        print()
        print("Check the errors above and verify:")
        print(f"  1. You're running from project root: {project_root}")
        print(f"  2. Source files exist in: {scripts_src} and {effects_src}")
    
    return success


def install_dependencies():
    """Install Python dependencies."""
    print("\n" + "="*60)
    print("INSTALLING PYTHON DEPENDENCIES")
    print("="*60 + "\n")
    
    try:
        # Upgrade pip
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        
        # Install from requirements.txt if it exists
        requirements_file = Path("requirements.txt")
        if requirements_file.exists():
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            print("\n[OK] Dependencies installed from requirements.txt")
        else:
            print("[WARNING] requirements.txt not found")
            print("Installing core dependencies...")
            # Install essential packages
            core_packages = ["numpy<2.0", "mido", "xmlrpc"]
            for package in core_packages:
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", package])
                except:
                    print(f"[WARNING] Could not install {package}")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Dependency installation failed: {e}")
        return False


def check_current_installation():
    """Check what's currently installed in REAPER."""
    print("\n" + "="*60)
    print("CHECKING CURRENT INSTALLATION")
    print("="*60 + "\n")
    
    if platform.system() == "Darwin":
        reaper_path = Path.home() / "Library/Application Support/REAPER"
    elif platform.system() == "Windows":
        reaper_path = Path.home() / "AppData/Roaming/REAPER"
    else:
        reaper_path = Path.home() / ".config/REAPER"
    
    if not reaper_path.exists():
        print(f"REAPER directory not found at: {reaper_path}")
        return
    
    print(f"REAPER directory: {reaper_path}\n")
    
    # Check key MMM files
    mmm_files = [
        ("Scripts/composers_assistant_v2/rpr_mmm_functions.py", "Script"),
        ("Scripts/composers_assistant_v2/mmm_nn_server.py", "Script"),
        ("Effects/composers_assistant_v2/MMM Track Options.js", "Effect"),
        ("Effects/composers_assistant_v2/MMM Global Options", "Effect"),
    ]
    
    installed_count = 0
    for file_path, file_type in mmm_files:
        full_path = reaper_path / file_path
        if full_path.exists():
            print(f"  [✓] {file_type}: {file_path}")
            installed_count += 1
        else:
            print(f"  [✗] {file_type}: {file_path}")
    
    print(f"\nMMM Files: {installed_count}/{len(mmm_files)} installed")


def main():
    print("\n" + "="*60)
    print("MMM SETUP FOR REAPER")
    print("="*60)
    
    # Check current installation
    check_current_installation()
    
    # Ask what to do
    print("\n" + "-"*60)
    print("\nOptions:")
    print("  1. Install REAPER integration (copy files)")
    print("  2. Install Python dependencies")
    print("  3. Both (recommended for first-time setup)")
    print("  4. Exit")
    
    choice = input("\nYour choice (1-4): ").strip()
    
    if choice == "1":
        setup_reaper_integration()
    elif choice == "2":
        install_dependencies()
    elif choice == "3":
        deps_ok = install_dependencies()
        if deps_ok:
            print("\nProceeding to REAPER integration...")
            setup_reaper_integration()
        else:
            print("\n[WARNING] Dependency installation had issues")
            proceed = input("Continue with REAPER setup anyway? (y/n): ")
            if proceed.lower() in ['y', 'yes']:
                setup_reaper_integration()
    elif choice == "4":
        print("Setup cancelled")
    else:
        print("Invalid choice")
    
    print("\n" + "="*60)
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()