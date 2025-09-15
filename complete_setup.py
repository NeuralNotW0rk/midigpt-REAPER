#!/usr/bin/env python3
"""
Composer's Assistant v2 - Complete Setup Script
Automated setup for virtual environment, dependencies, MIDI-GPT, and REAPER integration
"""

import os
import sys
import subprocess
import shutil
import platform
from pathlib import Path
import urllib.request
import zipfile

# Configuration
VENV_NAME = "venv"
PYTHON_MIN_VERSION = (3, 9)
MIDIGPT_REPO = "https://github.com/Metacreation-Lab/MIDI-GPT.git"

def run_command(cmd, check=True, capture_output=False, cwd=None):
    """Run a shell command with error handling"""
    try:
        result = subprocess.run(cmd, shell=True, check=check, 
                              capture_output=capture_output, text=True, cwd=cwd)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {cmd}")
        if capture_output:
            print(f"Error: {e.stderr}")
        sys.exit(1)

def check_python():
    """Check if Python 3.9+ is available"""
    print("Checking Python version...")
    
    # Try different Python commands
    for cmd in ["python3.9", "python3", "python"]:
        try:
            result = run_command(f"{cmd} --version", capture_output=True)
            version_str = result.stdout.strip()
            
            # Extract version numbers
            if "Python" in version_str:
                version_parts = version_str.split()[1].split('.')
                major, minor = int(version_parts[0]), int(version_parts[1])
                
                if (major, minor) >= PYTHON_MIN_VERSION:
                    print(f"Compatible Python found: {version_str}")
                    return cmd
        except:
            continue
    
    print(f"Python {PYTHON_MIN_VERSION[0]}.{PYTHON_MIN_VERSION[1]}+ not found")
    print("Install Python 3.9+:")
    print("  macOS: brew install python@3.9")
    print("  Ubuntu: sudo apt install python3.9 python3.9-venv")
    sys.exit(1)

def check_cuda():
    """Check if CUDA is available"""
    try:
        run_command("nvidia-smi", capture_output=True)
        print("CUDA detected")
        return True
    except:
        print("No CUDA detected - using CPU-only PyTorch")
        return False

def setup_venv(python_cmd):
    """Create virtual environment"""
    venv_path = Path(VENV_NAME)
    
    if venv_path.exists():
        print(f"Virtual environment exists: {VENV_NAME}")
        return
    
    print("Creating virtual environment...")
    run_command(f"{python_cmd} -m venv {VENV_NAME}")
    print(f"Virtual environment created: {VENV_NAME}")

def get_pip_command():
    """Get pip command for the virtual environment"""
    if platform.system() == "Windows":
        return f"{VENV_NAME}\\Scripts\\pip"
    else:
        return f"{VENV_NAME}/bin/pip"

def get_python_command():
    """Get Python command for the virtual environment"""
    if platform.system() == "Windows":
        return f".\\{VENV_NAME}\\Scripts\\python"
    else:
        return f"./{VENV_NAME}/bin/python"

def install_core_dependencies(has_cuda=False):
    """Install core Python dependencies"""
    pip_cmd = get_pip_command()
    
    print("Upgrading pip...")
    run_command(f"{pip_cmd} install --upgrade pip setuptools wheel")
    
    print("Installing core dependencies...")
    
    # Install PyTorch
    if has_cuda:
        print("Installing PyTorch with CUDA...")
        torch_cmd = (f'{pip_cmd} install torch>=2.0.0 torchvision torchaudio '
                    f'--index-url https://download.pytorch.org/whl/cu118')
    else:
        print("Installing CPU-only PyTorch...")
        torch_cmd = (f'{pip_cmd} install torch>=2.0.0 torchvision torchaudio '
                    f'--index-url https://download.pytorch.org/whl/cpu')
    
    run_command(torch_cmd)
    
    # Install other core dependencies
    deps = [
        'numpy>=1.21.0,<2.0',
        'protobuf>=4.0.0', 
        'pybind11[global]>=2.12.0',
        'transformers>=4.30.0',
        'cmake>=3.16.0',
        'tqdm'
    ]
    
    for dep in deps:
        run_command(f'{pip_cmd} install "{dep}"')

def clone_midi_gpt():
    """Clone MIDI-GPT repository from the python-3-9-refactor branch"""
    if Path("MIDI-GPT").exists():
        print("MIDI-GPT repository already exists")
        # Check if we're on the correct branch
        try:
            result = run_command("git branch --show-current", capture_output=True, cwd="MIDI-GPT")
            current_branch = result.stdout.strip()
            if current_branch != "python-3-9-refactor":
                print(f"MIDI-GPT is on branch '{current_branch}', switching to 'python-3-9-refactor'...")
                run_command("git fetch origin", cwd="MIDI-GPT")
                run_command("git checkout python-3-9-refactor", cwd="MIDI-GPT")
                print("Switched to python-3-9-refactor branch")
            else:
                print("Already on python-3-9-refactor branch")
        except:
            print("Could not check/switch branch - manual intervention may be required")
        return
    
    print("Cloning MIDI-GPT repository (python-3-9-refactor branch)...")
    run_command(f"git clone -b python-3-9-refactor {MIDIGPT_REPO}")
    print("MIDI-GPT repository cloned from python-3-9-refactor branch")

def build_midi_gpt():
    """Build MIDI-GPT using setup_midigpt.py with --install flag for automatic environment installation"""
    if not Path("MIDI-GPT").exists():
        print("MIDI-GPT repository not found")
        return False
    
    # Check if setup_midigpt.py exists
    setup_script = Path("MIDI-GPT/setup_midigpt.py")
    if not setup_script.exists():
        print("setup_midigpt.py not found in MIDI-GPT directory")
        print("This usually means the wrong branch was cloned.")
        print("Expected branch: python-3-9-refactor")
        print("\nTry manually:")
        print("  cd MIDI-GPT")
        print("  git fetch origin")
        print("  git checkout python-3-9-refactor")
        return False
    
    print("Building and installing MIDI-GPT...")
    
    # Get absolute path to virtual environment python
    current_dir = Path.cwd()
    venv_python_path = current_dir / VENV_NAME / "bin" / "python"
    if platform.system() == "Windows":
        venv_python_path = current_dir / VENV_NAME / "Scripts" / "python.exe"
    
    if not venv_python_path.exists():
        print(f"Virtual environment Python not found: {venv_python_path}")
        print("Try activating the virtual environment first:")
        print(f"  source {VENV_NAME}/bin/activate")
        return False
    
    # Use the --install flag to automatically install to current environment
    build_flags = ["--install", "--test"]
    if platform.system() == "Darwin":
        build_flags.append("--mac-os")
    
    build_cmd = f"{venv_python_path} setup_midigpt.py {' '.join(build_flags)}"
    
    try:
        run_command(build_cmd, cwd="MIDI-GPT")
        print("MIDI-GPT built and installed successfully")
        return True
    except:
        print("MIDI-GPT build with --install failed")
        print("Trying fallback without --install flag...")
        
        # Fallback to build-only approach
        fallback_flags = ["--test"]
        if platform.system() == "Darwin":
            fallback_flags.append("--mac-os")
        
        fallback_cmd = f"{venv_python_path} setup_midigpt.py {' '.join(fallback_flags)}"
        
        try:
            run_command(fallback_cmd, cwd="MIDI-GPT")
            print("MIDI-GPT built successfully (manual path setup required)")
            return True
        except:
            print("Both build attempts failed")
            print("Manual completion required:")
            print(f"  source {VENV_NAME}/bin/activate")
            print(f"  cd MIDI-GPT && python setup_midigpt.py --install --test")
            return False

def find_reaper_path():
    """Find REAPER resources directory"""
    system = platform.system()
    
    if system == "Darwin":  # macOS
        paths = [
            Path.home() / "Library/Application Support/REAPER",
            "/Library/Application Support/REAPER"
        ]
    elif system == "Windows":
        paths = [
            Path.home() / "AppData/Roaming/REAPER",
            Path("C:/Program Files/REAPER/InstallData")
        ]
    else:  # Linux
        paths = [
            Path.home() / ".config/REAPER",
            Path("/opt/REAPER")
        ]
    
    for path in paths:
        if path.exists():
            return path
    
    return None

def setup_reaper_integration():
    """Setup REAPER symlinks"""
    reaper_path = find_reaper_path()
    if not reaper_path:
        print("REAPER installation not found - skipping integration")
        return
    
    print(f"Setting up REAPER integration at: {reaper_path}")
    
    # Create symlinks
    project_root = Path.cwd()
    scripts_src = project_root / "Scripts"
    effects_src = project_root / "Effects"
    
    scripts_dst = reaper_path / "Scripts/composers_assistant_v2"
    effects_dst = reaper_path / "Effects/composers_assistant_v2"
    
    # Create Scripts symlink
    if scripts_src.exists():
        if scripts_dst.exists():
            scripts_dst.unlink()
        scripts_dst.symlink_to(scripts_src)
        print(f"Scripts symlinked: {scripts_dst}")
    
    # Create Effects symlink  
    if effects_src.exists():
        if effects_dst.exists():
            effects_dst.unlink()
        effects_dst.symlink_to(effects_src)
        print(f"Effects symlinked: {effects_dst}")

def download_models():
    """Download required models if not present"""
    models_dir = Path("models")
    if not models_dir.exists():
        models_dir.mkdir()
    
    # Check if models are already present
    if any(models_dir.glob("*.bin")) or any(models_dir.glob("*.pth")):
        print("Models already present")
        return
    
    print("Model download would occur here - implement as needed")

def verify_installation():
    """Verify all components are working"""
    print("\nVerifying installation...")
    
    # Get absolute path to virtual environment python
    current_dir = Path.cwd()
    venv_python_path = current_dir / VENV_NAME / "bin" / "python"
    if platform.system() == "Windows":
        venv_python_path = current_dir / VENV_NAME / "Scripts" / "python.exe"
    
    if not venv_python_path.exists():
        print(f"Virtual environment Python not found: {venv_python_path}")
        print("Using fallback system python for verification")
        python_cmd = "python"
    else:
        python_cmd = str(venv_python_path)
    
    # Test core imports
    test_imports = [
        ("import torch", "PyTorch"),
        ("import numpy", "NumPy"), 
        ("import transformers", "Transformers")
    ]
    
    for test_cmd, name in test_imports:
        try:
            run_command(f'{python_cmd} -c "{test_cmd}"', capture_output=True)
            print(f"  ✓ {name}")
        except:
            print(f"  ✗ {name}")
    
    # Test MIDI-GPT import
    try:
        # With --install flag, midigpt should be directly importable
        run_command(f'{python_cmd} -c "import midigpt; print(\\"MIDI-GPT: Ready\\")"', capture_output=True)
        print("  ✓ MIDI-GPT import (installed)")
    except:
        # Fallback to path-based import
        try:
            midi_test_cmd = f'{python_cmd} -c "import sys; sys.path.append(\\"MIDI-GPT/python_lib\\"); import midigpt; print(\\"MIDI-GPT: Ready\\")"'
            run_command(midi_test_cmd, capture_output=True)
            print("  ✓ MIDI-GPT import (path-based)")
        except:
            print("  ✗ MIDI-GPT import - requires manual completion")

def print_completion_message():
    """Print completion message and next steps"""
    activate_cmd = f"source {VENV_NAME}/bin/activate"
    if platform.system() == "Windows":
        activate_cmd = f"{VENV_NAME}\\Scripts\\activate"
    
    print("\n" + "="*50)
    print("Setup Complete!")
    print("="*50)
    print(f"\nTo activate the environment: {activate_cmd}")
    print("\nNext steps:")
    print("1. Start the server: python start_unified.py start")
    print("2. Open REAPER and load Composer's Assistant scripts")
    print("3. Begin composing with AI assistance!")
    
    print(f"\nFor manual MIDI-GPT completion if needed:")
    print(f"  {activate_cmd}")
    print(f"  cd MIDI-GPT && python setup_midigpt.py --install --test")
    if platform.system() == "Darwin":
        print(f"  (on macOS: python setup_midigpt.py --install --mac-os --test)")
    
    print(f"\nTo verify your virtual environment is working:")
    print(f"  {activate_cmd}")
    print(f"  python -c \"import sys; print(sys.executable)\"")
    print(f"  python -c \"import transformers; print('Transformers OK')\"")



def main():
    print("Composer's Assistant v2 - Complete Setup")
    print("=" * 50)
    
    try:
        # Environment setup
        python_cmd = check_python()
        has_cuda = check_cuda()
        setup_venv(python_cmd)
        
        # Dependencies
        install_core_dependencies(has_cuda)
        
        # MIDI-GPT integration
        clone_midi_gpt()
        midi_success = build_midi_gpt()
        
        # REAPER integration
        setup_reaper_integration()
        
        # Models
        download_models()
        
        # Verification
        verify_installation()
        
        # Completion
        print_completion_message()
        
        if not midi_success:
            print("\nNote: MIDI-GPT build may require manual completion")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\nSetup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nSetup failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()