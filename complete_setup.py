#!/usr/bin/env python3
"""
Composer's Assistant v2 - Complete Setup Script
Fixed version with proper NumPy constraint handling
"""

import os
import sys
import subprocess
import shutil
import platform
from pathlib import Path

VENV_NAME = "venv"
PYTHON_MIN_VERSION = (3, 9)
MIDIGPT_REPO = "https://github.com/Metacreation-Lab/MIDI-GPT.git"

def run_command(cmd, capture_output=False, cwd=None):
    """Run command with proper error handling and shell escaping"""
    try:
        if isinstance(cmd, str):
            # For string commands, use shell=True but be careful with escaping
            result = subprocess.run(cmd, shell=True, check=True, 
                                  capture_output=capture_output, text=True, cwd=cwd)
        else:
            # For list commands, no shell needed
            result = subprocess.run(cmd, check=True, 
                                  capture_output=capture_output, text=True, cwd=cwd)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {cmd}")
        print(f"Error: {e}")
        if capture_output:
            print(f"Output: {e.stdout}")
            print(f"Error: {e.stderr}")
        raise

def check_python():
    """Check for compatible Python version"""
    print("Checking Python version...")
    
    python_commands = ["python3.9", "python3", "python"]
    
    for cmd in python_commands:
        try:
            result = run_command(f"{cmd} --version", capture_output=True)
            version_str = result.stdout.strip()
            
            # Extract version numbers
            version_parts = version_str.split()[-1].split('.')
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
        return Path(VENV_NAME) / "Scripts" / "pip"
    else:
        return Path(VENV_NAME) / "bin" / "pip"

def get_python_command():
    """Get Python command for the virtual environment"""
    current_dir = Path.cwd()
    if platform.system() == "Windows":
        return str(current_dir / VENV_NAME / "Scripts" / "python")
    else:
        return str(current_dir / VENV_NAME / "bin" / "python")

def install_core_dependencies(has_cuda=False):
    """Install core Python dependencies with proper constraint handling"""
    pip_cmd = str(get_pip_command())
    
    print("Upgrading pip...")
    run_command([pip_cmd, "install", "--upgrade", "pip", "setuptools", "wheel"])
    
    print("Installing core dependencies...")
    
    # Install PyTorch - use list format to avoid shell parsing issues
    if has_cuda:
        print("Installing PyTorch with CUDA...")
        run_command([pip_cmd, "install", "torch>=2.0.0", "torchvision", "torchaudio", 
                    "--index-url", "https://download.pytorch.org/whl/cu118"])
    else:
        print("Installing CPU-only PyTorch...")
        run_command([pip_cmd, "install", "torch>=2.0.0", "torchvision", "torchaudio",
                    "--index-url", "https://download.pytorch.org/whl/cpu"])
    
    # Install other core dependencies - use list format to prevent shell interpretation of <>
    deps = [
        ("numpy", "numpy==1.26.4"),        # Critical: constraint NumPy to 1.x
        ("protobuf", "protobuf>=4.0.0"), 
        ("pybind11", "pybind11[global]>=2.12.0"),
        ("transformers", "transformers==4.41.0"),
        ("cmake", "cmake>=3.16.0"),
        ("tqdm", "tqdm")
    ]
    
    for name, constraint in deps:
        print(f"Installing {constraint}...")
        # Use list format instead of string to avoid shell parsing of < > symbols
        run_command([pip_cmd, "install", constraint])

def install_project_requirements():
    """Install project-specific requirements"""
    pip_cmd = str(get_pip_command())
    
    # Install MIDI libraries
    midi_libs = ["mido>=1.1.16", "miditoolkit"]
    
    for lib in midi_libs:
        print(f"Installing {lib}...")
        run_command([pip_cmd, "install", lib])
    
    # Install other project requirements
    other_libs = ["portion", "sentencepiece", "matplotlib"]
    
    for lib in other_libs:
        print(f"Installing {lib}...")
        run_command([pip_cmd, "install", lib])

def clone_midi_gpt():
    """Clone MIDI-GPT repository from the python-3-9-refactor branch"""
    if Path("MIDI-GPT").exists():
        print("MIDI-GPT repository already exists")
        # Check if we're on the correct branch
        try:
            result = run_command("git branch --show-current", capture_output=True, cwd="MIDI-GPT")
            current_branch = result.stdout.strip()
            if current_branch != "python-3-9-refactor":
                print(f"Switching from {current_branch} to python-3-9-refactor branch...")
                run_command("git checkout python-3-9-refactor", cwd="MIDI-GPT")
            else:
                print("Already on python-3-9-refactor branch")
        except:
            print("Could not determine current branch, proceeding with existing repo")
        return
    
    print("Cloning MIDI-GPT repository (python-3-9-refactor branch)...")
    run_command(f"git clone -b python-3-9-refactor {MIDIGPT_REPO}")
    print("MIDI-GPT repository cloned from python-3-9-refactor branch")

def build_midi_gpt():
    """Build and install MIDI-GPT using the --install flag"""
    print("Building and installing MIDI-GPT...")
    
    if not Path("MIDI-GPT").exists():
        print("MIDI-GPT directory not found")
        return False
    
    python_cmd = str(get_python_command())
    
    try:
        # Use the new --install flag for direct installation to venv
        if platform.system() == "Darwin":  # macOS
            run_command([python_cmd, "setup_midigpt.py", "--install", "--mac-os", "--test"], 
                       cwd="MIDI-GPT")
        else:
            run_command([python_cmd, "setup_midigpt.py", "--install", "--test"], 
                       cwd="MIDI-GPT")
        
        print("MIDI-GPT built and installed successfully")
        return True
        
    except Exception as e:
        print(f"MIDI-GPT build failed: {e}")
        print("You may need to complete this manually:")
        print(f"  cd MIDI-GPT && {python_cmd} setup_midigpt.py --install --test")
        return False

def setup_reaper_integration():
    """Setup REAPER integration"""
    if platform.system() == "Darwin":  # macOS
        reaper_path = Path.home() / "Library/Application Support/REAPER"
    elif platform.system() == "Windows":
        reaper_path = Path.home() / "AppData/Roaming/REAPER"
    else:  # Linux
        reaper_path = Path.home() / ".config/REAPER"
    
    if not reaper_path.exists():
        print(f"REAPER not found at {reaper_path}")
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
    python_cmd = str(get_python_command())
    
    # Test core imports
    test_imports = [
        ("import torch", "PyTorch"),
        ("import numpy", "NumPy"), 
        ("import transformers", "Transformers")
    ]
    
    for test_cmd, name in test_imports:
        try:
            run_command([python_cmd, "-c", test_cmd], capture_output=True)
            print(f"  ✓ {name}")
        except:
            print(f"  ✗ {name}")
    
    # Test MIDI-GPT import
    try:
        # With --install flag, midigpt should be directly importable
        run_command([python_cmd, "-c", "import midigpt; print('MIDI-GPT: Ready')"], 
                   capture_output=True)
        print("  ✓ MIDI-GPT import (installed)")
    except:
        # Fallback to path-based import
        try:
            midi_test_cmd = 'import sys; sys.path.append("MIDI-GPT/python_lib"); import midigpt; print("MIDI-GPT: Ready")'
            run_command([python_cmd, "-c", midi_test_cmd], capture_output=True)
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
    print("1. Start the server: python start_server.py start")
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
    print(f"  python -c \"import numpy; print('NumPy:', numpy.__version__)\"")

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
        install_project_requirements()
        
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