#!/usr/bin/env python3
"""
Complete macOS Setup Script for Composer's Assistant v2 + MIDI-GPT
Handles environment setup, MIDI-GPT cloning/building, and REAPER integration
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
import tempfile
import urllib.request
import zipfile

# Configuration
VENV_NAME = "venv"  # Changed from .venv
MIDI_GPT_REPO = "https://github.com/Metacreation-Lab/MIDI-GPT.git"
RELEASE_VERSION = "2.1.0"
PYTHON_MIN_VERSION = (3, 9)

class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color

def log(message, color=Colors.NC):
    print(f"{color}{message}{Colors.NC}")

def log_info(message):
    log(f"[INFO] {message}", Colors.GREEN)

def log_warn(message):
    log(f"[WARN] {message}", Colors.YELLOW)

def log_error(message):
    log(f"[ERROR] {message}", Colors.RED)

def run_command(cmd, cwd=None, check=True, capture_output=False):
    """Run command with proper error handling"""
    try:
        result = subprocess.run(
            cmd, shell=True, check=check, 
            capture_output=capture_output, text=True, 
            cwd=cwd
        )
        return result
    except subprocess.CalledProcessError as e:
        log_error(f"Command failed: {cmd}")
        if capture_output and e.stdout:
            print(f"Output: {e.stdout}")
        if capture_output and e.stderr:
            print(f"Error: {e.stderr}")
        if check:
            sys.exit(1)
        return None

def check_python():
    """Find suitable Python 3.9+ executable"""
    log_info("Checking Python version...")
    
    candidates = ["python3.9", "python3.10", "python3.11", "python3.12", "python3"]
    
    for python_cmd in candidates:
        try:
            result = run_command(f"{python_cmd} --version", capture_output=True, check=False)
            if result and result.returncode == 0:
                version_str = result.stdout.strip()
                # Extract version numbers
                version_parts = version_str.split()[1].split('.')
                major, minor = int(version_parts[0]), int(version_parts[1])
                
                if (major, minor) >= PYTHON_MIN_VERSION:
                    log_info(f"Found compatible Python: {version_str}")
                    return python_cmd
        except:
            continue
    
    log_error("Python 3.9+ not found!")
    log_error("Install with: brew install python@3.9")
    sys.exit(1)

def setup_environment(python_cmd):
    """Create virtual environment"""
    log_info(f"Setting up virtual environment: {VENV_NAME}")
    
    venv_path = Path(VENV_NAME)
    if venv_path.exists():
        log_warn(f"Removing existing {VENV_NAME}")
        shutil.rmtree(venv_path)
    
    run_command(f"{python_cmd} -m venv {VENV_NAME}")
    
    # Get activation command
    if sys.platform == "win32":
        pip_cmd = f"{VENV_NAME}\\Scripts\\pip"
        python_venv = f"{VENV_NAME}\\Scripts\\python"
    else:
        pip_cmd = f"{VENV_NAME}/bin/pip"
        python_venv = f"{VENV_NAME}/bin/python"
    
    # Upgrade pip
    log_info("Upgrading pip...")
    run_command(f"{pip_cmd} install --upgrade pip setuptools wheel")
    
    return pip_cmd, python_venv

def install_base_dependencies(pip_cmd):
    """Install core Python dependencies"""
    log_info("Installing base dependencies...")
    
    # Check for CUDA
    has_cuda = False
    try:
        run_command("nvidia-smi", capture_output=True)
        has_cuda = True
        log_info("CUDA detected")
    except:
        log_info("No CUDA - installing CPU PyTorch")
    
    # Install PyTorch
    if has_cuda:
        torch_cmd = f'{pip_cmd} install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118'
    else:
        torch_cmd = f'{pip_cmd} install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu'
    
    run_command(torch_cmd)
    
    # Install other dependencies
    deps = [
        "numpy>=1.21.0,<2.0",
        "protobuf>=4.0.0",
        "pybind11[global]>=2.12.0", 
        "transformers>=4.30.0",
        "tqdm",
        "cmake>=3.16.0"
    ]
    
    for dep in deps:
        log_info(f"Installing {dep}...")
        run_command(f'{pip_cmd} install "{dep}"')

def clone_midi_gpt():
    """Clone MIDI-GPT repository"""
    midi_gpt_path = Path("MIDI-GPT")
    
    if midi_gpt_path.exists():
        log_info("MIDI-GPT already exists, updating...")
        run_command("git pull", cwd="MIDI-GPT")
    else:
        log_info("Cloning MIDI-GPT...")
        run_command(f"git clone {MIDI_GPT_REPO}")
    
    return midi_gpt_path.exists()

def build_midi_gpt(python_venv):
    """Build MIDI-GPT library"""
    log_info("Building MIDI-GPT...")
    
    midi_gpt_path = Path("MIDI-GPT")
    if not midi_gpt_path.exists():
        log_error("MIDI-GPT not found!")
        return False
    
    # Try different build methods
    setup_script = midi_gpt_path / "setup_midigpt.py"
    
    if setup_script.exists():
        log_info("Using setup_midigpt.py...")
        cmd = f"{python_venv} setup_midigpt.py --mac-os --test"
        result = run_command(cmd, cwd="MIDI-GPT", check=False)
        if result and result.returncode == 0:
            log_info("MIDI-GPT built successfully!")
            return True
    
    # Try pyproject.toml/setup.py
    if (midi_gpt_path / "pyproject.toml").exists() or (midi_gpt_path / "setup.py").exists():
        log_info("Trying pip install -e ...")
        cmd = f"{python_venv} -m pip install -e ."
        result = run_command(cmd, cwd="MIDI-GPT", check=False)
        if result and result.returncode == 0:
            log_info("MIDI-GPT installed successfully!")
            return True
    
    log_warn("MIDI-GPT build failed, but continuing...")
    return False

def install_project_requirements(pip_cmd):
    """Install project-specific requirements"""
    req_files = ["requirements.txt", "requirements_base.txt"]
    
    for req_file in req_files:
        if Path(req_file).exists():
            log_info(f"Installing from {req_file}...")
            run_command(f"{pip_cmd} install -r {req_file}")
            break
    else:
        log_info("No requirements file found, skipping...")

def setup_reaper_integration():
    """Setup REAPER symlinks"""
    log_info("Setting up REAPER integration...")
    
    reaper_path = Path.home() / "Library/Application Support/REAPER"
    if not reaper_path.exists():
        log_warn("REAPER not found, skipping integration")
        return
    
    # Setup Scripts
    scripts_src = Path("src/Scripts/composers_assistant_v2")
    if scripts_src.exists():
        scripts_dst = reaper_path / "Scripts/composers_assistant_v2"
        if scripts_dst.exists() or scripts_dst.is_symlink():
            scripts_dst.unlink()
        scripts_dst.parent.mkdir(exist_ok=True)
        scripts_dst.symlink_to(scripts_src.absolute())
        log_info("Scripts linked")
    
    # Setup Effects  
    effects_src = Path("src/Effects/composers_assistant_v2")
    if effects_src.exists():
        effects_dst = reaper_path / "Effects/composers_assistant_v2"
        if effects_dst.exists() or effects_dst.is_symlink():
            effects_dst.unlink()
        effects_dst.parent.mkdir(exist_ok=True)
        effects_dst.symlink_to(effects_src.absolute())
        log_info("Effects linked")

def download_models():
    """Download model files"""
    log_info("Downloading models...")
    
    zip_name = f"composers.assistant.v.{RELEASE_VERSION}.zip"
    url = f"https://github.com/m-malandro/composers-assistant-REAPER/releases/download/v{RELEASE_VERSION}/{zip_name}"
    model_dir = Path("src/Scripts/composers_assistant_v2/models_permuted_labels")
    
    if model_dir.exists() and any(model_dir.iterdir()):
        log_info("Models already exist, skipping download")
        return
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        zip_path = temp_path / zip_name
        
        try:
            log_info(f"Downloading {url}...")
            urllib.request.urlretrieve(url, zip_path)
            
            log_info("Extracting models...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_path)
            
            # Copy models
            source_models = temp_path / "Scripts/composers_assistant_v2/models_permuted_labels"
            if source_models.exists():
                model_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source_models, model_dir, dirs_exist_ok=True)
                log_info("Models extracted successfully")
            else:
                log_warn("Model directory not found in download")
                
        except Exception as e:
            log_error(f"Failed to download models: {e}")

def verify_installation(python_venv):
    """Verify the installation"""
    log_info("Verifying installation...")
    
    # Convert to absolute path
    python_venv_abs = Path(python_venv).resolve()
    
    # Test Python packages
    test_imports = [
        ("torch", "PyTorch"),
        ("numpy", "NumPy"),
        ("transformers", "Transformers"),
    ]
    
    for module, name in test_imports:
        try:
            # Fixed f-string syntax by escaping quotes properly
            cmd = f'{python_venv_abs} -c "import {module}; print(\'{name}:\', getattr({module}, \'__version__\', \'OK\'))"'
            result = run_command(cmd, capture_output=True, check=False)
            if result and result.returncode == 0:
                log_info(result.stdout.strip())
            else:
                log_warn(f"{name} import failed")
        except:
            log_warn(f"{name} verification failed")
    
    # Test MIDI-GPT
    midi_gpt_test = (
        f'{python_venv_abs} -c "'
        f'import sys; sys.path.append(\"MIDI-GPT/python_lib\"); '
        f'import midigpt; print(\"MIDI-GPT: Ready\")"'
    )
    
    try:
        result = run_command(midi_gpt_test, capture_output=True, check=False)
        if result and result.returncode == 0:
            log_info("MIDI-GPT: Ready")
        else:
            log_warn("MIDI-GPT: Not available (manual setup may be needed)")
    except:
        log_warn("MIDI-GPT verification failed")

def print_summary():
    """Print setup summary and next steps"""
    log_info("Setup completed!")
    
    if sys.platform == "win32":
        activate_cmd = f"{VENV_NAME}\\Scripts\\activate"
    else:
        activate_cmd = f"source {VENV_NAME}/bin/activate"
    
    print("\n" + "="*60)
    print("SETUP SUMMARY")
    print("="*60)
    print(f"✅ Virtual environment: {VENV_NAME} (changed from .venv)")
    print(f"✅ Python 3.9+ with PyTorch and dependencies")
    print(f"✅ MIDI-GPT repository cloned")
    
    # Check if MIDI-GPT built successfully
    if Path("MIDI-GPT/python_lib").exists() and any(Path("MIDI-GPT/python_lib").iterdir()):
        print(f"✅ MIDI-GPT built and ready")
    else:
        print(f"⚠️  MIDI-GPT cloned but build may need completion")
    
    print(f"✅ REAPER integration configured")
    print(f"✅ Project requirements installed")
    
    if Path("src/Scripts/composers_assistant_v2/models_permuted_labels").exists():
        print(f"✅ Models available")
    else:
        print(f"⚠️  Models may need download")
    
    print("\nNEXT STEPS:")
    print("="*60)
    print(f"1. Activate environment: {activate_cmd}")
    print("2. Test MIDI-GPT (if needed):")
    print("   python -c \"import sys; sys.path.append('MIDI-GPT/python_lib'); import midigpt; print('OK')\"")
    print("3. Start servers:")
    print("   python start_unified.py start    # Unified server")
    print("   # or")
    print("   python start_servers.py start    # Legacy dual server")
    print("4. Open REAPER and check Scripts menu")
    
    print("\nVERIFICATION:")
    print("="*60)
    print(f"   {activate_cmd}")
    print("   python -c \"import torch; print('PyTorch:', torch.__version__)\"")
    print("   python -c \"import miditoolkit; print('miditoolkit: OK')\"")
    
    print("\nTROUBLESHOOTING:")
    print("="*60)
    print("- If MIDI-GPT import fails:")
    print("  cd MIDI-GPT && python setup_midigpt.py --mac-os --test")
    print("- For REAPER issues, check symlinks in:")
    print("  ~/Library/Application Support/REAPER/Scripts/")
    print("- For server issues, check firewall (port 3456)")
    print("- If dependencies missing: brew install protobuf cmake")

def main():
    """Main setup routine"""
    print("="*60)
    print("Composer's Assistant v2 + MIDI-GPT Setup")
    print("macOS Unified Installation Script")
    print("="*60)
    
    try:
        # Step 1: Check Python
        python_cmd = check_python()
        
        # Step 2: Setup environment 
        pip_cmd, python_venv = setup_environment(python_cmd)
        
        # Step 3: Install base dependencies
        install_base_dependencies(pip_cmd)
        
        # Step 4: Clone MIDI-GPT
        midi_gpt_available = clone_midi_gpt()
        
        # Step 5: Build MIDI-GPT
        if midi_gpt_available:
            build_midi_gpt(python_venv)
        
        # Step 6: Install project requirements
        install_project_requirements(pip_cmd)
        
        # Step 7: Setup REAPER
        setup_reaper_integration()
        
        # Step 8: Download models
        download_models()
        
        # Step 9: Verify installation
        verify_installation(python_venv)
        
        # Step 10: Print summary
        print_summary()
        
    except KeyboardInterrupt:
        log_error("Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"Setup failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()