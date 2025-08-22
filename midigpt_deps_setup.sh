#!/bin/bash

# MidiGPT Setup with Custom Dependencies
# Downloads cmake=3.23.1 and protobuf=3.12.3, then runs the original setup

set -e  # Exit on any error

# Configuration
DEPS_DIR="$(pwd)/midigpt_dependencies"
CMAKE_VERSION="3.23.1"
PROTOBUF_VERSION="3.12.3"
NUM_CORES=$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo "4")

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    printf "${BLUE}[INFO]${NC} %s\n" "$1"
}

success() {
    printf "${GREEN}[SUCCESS]${NC} %s\n" "$1"
}

warning() {
    printf "${YELLOW}[WARNING]${NC} %s\n" "$1"
}

error() {
    printf "${RED}[ERROR]${NC} %s\n" "$1"
}

# Parse arguments, filtering out -d and -c since we'll handle them automatically
SETUP_ARGS=""
REPO_DIR="midigpt_workspace"
REPLACE_REPO=false
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            echo "Custom MidiGPT Setup with specific cmake and protobuf versions"
            echo "This script downloads cmake=3.23.1 and protobuf=3.12.3, then runs midigpt_setup_helper.sh"
            echo ""
            echo "Simplified usage:"
            echo "  -h  Show this help text"
            echo "  -i  Setup repository for inference"
            echo "  -m  If on MacOS CPU"
            echo "  -n  Test the training script imports"
            echo "  -r  Replace repository directory if it already exists"
            echo "  -p  Provide python executable/path (default: python3)"
            echo ""
            echo "The repository will be cloned automatically if not present in './midigpt_workspace'"
            echo "Use -r to replace an existing repository"
            exit 0
            ;;
        -d)
            # Skip -d and its argument, we'll use our own directory
            shift
            if [[ $# -gt 0 ]]; then
                shift
            fi
            ;;
        -c)
            # Skip -c, we'll handle cloning automatically
            shift
            ;;
        -r)
            REPLACE_REPO=true
            SETUP_ARGS="$SETUP_ARGS $1"
            shift
            ;;
        -p)
            SETUP_ARGS="$SETUP_ARGS $1"
            shift
            if [[ $# -gt 0 ]]; then
                SETUP_ARGS="$SETUP_ARGS $1"
                shift
            fi
            ;;
        *)
            SETUP_ARGS="$SETUP_ARGS $1"
            shift
            ;;
    esac
done

# Determine if we need to clone
if [[ -d "$REPO_DIR" ]]; then
    if [[ "$REPLACE_REPO" == true ]]; then
        log "Repository exists but -r flag specified, will replace it"
        SETUP_ARGS="$SETUP_ARGS -c"
    else
        log "Repository already exists, will use existing one"
        # Don't add -c flag
    fi
else
    log "Repository doesn't exist, will clone it"
    SETUP_ARGS="$SETUP_ARGS -c"
fi

# Always add our consistent directory parameter
SETUP_ARGS="$SETUP_ARGS -d $REPO_DIR"

# Detect OS
detect_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macos"
        CMAKE_ARCH="macos-universal"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS="linux"
        CMAKE_ARCH="Linux-x86_64"
    else
        error "Unsupported OS: $OSTYPE"
        exit 1
    fi
    log "Detected OS: $OS"
}

# Create dependencies directory
setup_directories() {
    log "Setting up directory structure..."
    mkdir -p "$DEPS_DIR"
    mkdir -p "$DEPS_DIR/downloads"
    mkdir -p "$DEPS_DIR/build"
    mkdir -p "$DEPS_DIR/install"
    success "Directory structure created at $DEPS_DIR"
}

# Download cmake
download_cmake() {
    local cmake_dir="$DEPS_DIR/install/cmake"
    
    if [[ -f "$cmake_dir/bin/cmake" ]]; then
        log "CMake $CMAKE_VERSION already installed, skipping download"
        return 0
    fi
    
    log "Downloading CMake $CMAKE_VERSION..."
    local cmake_archive_name="cmake-$CMAKE_VERSION-$CMAKE_ARCH.tar.gz"
    local cmake_url="https://github.com/Kitware/CMake/releases/download/v$CMAKE_VERSION/$cmake_archive_name"
    local cmake_archive="$DEPS_DIR/downloads/$cmake_archive_name"
    
    if [[ ! -f "$cmake_archive" ]]; then
        log "Downloading from: $cmake_url"
        cd "$DEPS_DIR/downloads"
        curl -L -O "$cmake_url"
        cd - > /dev/null
        
        if [[ ! -f "$cmake_archive" ]]; then
            error "Failed to download CMake"
            exit 1
        fi
        
        # Verify the download
        local file_size=$(stat -f%z "$cmake_archive" 2>/dev/null || stat -c%s "$cmake_archive" 2>/dev/null)
        if [[ $file_size -lt 1000000 ]]; then
            error "Downloaded file seems too small ($file_size bytes). Download may have failed."
            rm -f "$cmake_archive"
            exit 1
        fi
        log "Downloaded $(($file_size / 1024 / 1024))MB successfully"
    fi
    
    log "Extracting CMake..."
    cd "$DEPS_DIR/downloads"
    
    # First, let's see what's in the archive
    log "Examining CMake archive contents..."
    tar -tzf "$cmake_archive_name" | head -10
    
    # Extract and see what we get
    tar -xzf "$cmake_archive_name"
    log "Contents after extraction:"
    ls -la
    
    # Find the actual cmake directory (might be named differently)
    local cmake_extracted_dir=$(find . -maxdepth 1 -name "cmake-*" -type d | head -1)
    if [[ -z "$cmake_extracted_dir" ]]; then
        error "Could not find extracted cmake directory"
        ls -la
        exit 1
    fi
    
    log "Found cmake directory: $cmake_extracted_dir"
    ls -la "$cmake_extracted_dir"
    
    # Move to final location
    mv "$cmake_extracted_dir" "$cmake_dir"
    rm -f "$cmake_archive_name"
    cd - > /dev/null
    
    # Verify the structure
    log "Final cmake directory structure:"
    ls -la "$cmake_dir"
    if [[ -d "$cmake_dir/CMake.app" ]]; then
        log "Found CMake.app bundle, extracting binary..."
        if [[ -f "$cmake_dir/CMake.app/Contents/bin/cmake" ]]; then
            # Copy the binary from the app bundle
            mkdir -p "$cmake_dir/bin"
            cp "$cmake_dir/CMake.app/Contents/bin/cmake" "$cmake_dir/bin/cmake"
            # Also copy any supporting files
            if [[ -d "$cmake_dir/CMake.app/Contents/share" ]]; then
                cp -r "$cmake_dir/CMake.app/Contents/share" "$cmake_dir/"
            fi
        fi
    fi
    
    # Ensure cmake binary is executable
    if [[ -f "$cmake_dir/bin/cmake" ]]; then
        chmod +x "$cmake_dir/bin/cmake"
    else
        error "CMake binary not found after extraction at $cmake_dir/bin/cmake"
        log "Directory contents:"
        find "$cmake_dir" -name "cmake" -type f
        exit 1
    fi
    
    # Test the binary works
    if ! "$cmake_dir/bin/cmake" --version > /dev/null 2>&1; then
        error "CMake binary is not working"
        exit 1
    fi
    
    success "CMake $CMAKE_VERSION installed to $cmake_dir"
}

# Download and build protobuf
download_build_protobuf() {
    local protobuf_dir="$DEPS_DIR/install/protobuf"
    local protobuf_src="$DEPS_DIR/build/protobuf"
    
    if [[ -f "$protobuf_dir/lib/libprotobuf.a" && -f "$protobuf_dir/bin/protoc" ]]; then
        log "Protobuf $PROTOBUF_VERSION already built, skipping"
        return 0
    fi
    
    log "Downloading Protobuf $PROTOBUF_VERSION..."
    local protobuf_archive_name="protobuf-all-$PROTOBUF_VERSION.tar.gz"
    local protobuf_url="https://github.com/protocolbuffers/protobuf/releases/download/v$PROTOBUF_VERSION/$protobuf_archive_name"
    local protobuf_archive="$DEPS_DIR/downloads/$protobuf_archive_name"
    
    if [[ ! -f "$protobuf_archive" ]]; then
        log "Downloading from: $protobuf_url"
        cd "$DEPS_DIR/downloads"
        curl -L -O "$protobuf_url"
        cd - > /dev/null
        
        if [[ ! -f "$protobuf_archive" ]]; then
            error "Failed to download Protobuf"
            exit 1
        fi
        
        # Verify the download
        local file_size=$(stat -f%z "$protobuf_archive" 2>/dev/null || stat -c%s "$protobuf_archive" 2>/dev/null)
        if [[ $file_size -lt 1000000 ]]; then
            error "Downloaded file seems too small ($file_size bytes). Download may have failed."
            rm -f "$protobuf_archive"
            exit 1
        fi
        log "Downloaded $(($file_size / 1024 / 1024))MB successfully"
    fi
    
    log "Extracting Protobuf..."
    cd "$DEPS_DIR/downloads"
    tar -xzf "$protobuf_archive_name"
    mv "protobuf-$PROTOBUF_VERSION" "$protobuf_src"
    rm -f "$protobuf_archive_name"
    cd - > /dev/null
    
    log "Building Protobuf (this may take several minutes)..."
    cd "$protobuf_src"
    
    # Configure
    ./configure --prefix="$protobuf_dir" --disable-shared --enable-static
    if [[ $? -ne 0 ]]; then
        error "Protobuf configure failed"
        exit 1
    fi
    
    # Build
    make -j$NUM_CORES
    if [[ $? -ne 0 ]]; then
        error "Protobuf build failed"
        exit 1
    fi
    
    # Install
    make install
    if [[ $? -ne 0 ]]; then
        error "Protobuf install failed"
        exit 1
    fi
    
    success "Protobuf $PROTOBUF_VERSION built and installed to $protobuf_dir"
    cd - > /dev/null
}

# Setup environment for custom dependencies
setup_environment() {
    log "Setting up environment for custom dependencies..."
    
    # Remove any existing cmake/protobuf paths from PATH to avoid conflicts
    export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v cmake | grep -v protobuf | tr '\n' ':' | sed 's/:$//')
    
    # Force our custom tools to be first in PATH
    export PATH="$DEPS_DIR/install/cmake/bin:$DEPS_DIR/install/protobuf/bin:$PATH"
    
    # Set protobuf environment variables
    export CMAKE_PREFIX_PATH="$DEPS_DIR/install/protobuf:$CMAKE_PREFIX_PATH"
    export Protobuf_ROOT="$DEPS_DIR/install/protobuf"
    export Protobuf_DIR="$DEPS_DIR/install/protobuf/lib/cmake/protobuf"
    export PKG_CONFIG_PATH="$DEPS_DIR/install/protobuf/lib/pkgconfig:$PKG_CONFIG_PATH"
    
    # Add protobuf lib to library path
    if [[ "$OSTYPE" == "darwin"* ]]; then
        export DYLD_LIBRARY_PATH="$DEPS_DIR/install/protobuf/lib:$DYLD_LIBRARY_PATH"
    else
        export LD_LIBRARY_PATH="$DEPS_DIR/install/protobuf/lib:$LD_LIBRARY_PATH"
    fi
    
    # Verify our tools are being used
    log "Verifying custom dependencies:"
    
    # Force hash table refresh for bash
    hash -r 2>/dev/null || true
    
    # Check if our cmake exists and is executable
    if [[ ! -x "$DEPS_DIR/install/cmake/bin/cmake" ]]; then
        error "Custom cmake binary not found or not executable"
        exit 1
    fi
    
    log "  Custom cmake binary: $DEPS_DIR/install/cmake/bin/cmake"
    log "  Custom cmake version: $($DEPS_DIR/install/cmake/bin/cmake --version | head -n1)"
    
    log "  CMake: $(cmake --version | head -n1)"
    log "  CMake path: $(which cmake)"
    if command -v protoc &> /dev/null; then
        log "  Protoc: $(protoc --version)"
        log "  Protoc path: $(which protoc)"
    else
        warning "protoc not found in PATH"
    fi
    log "  Protobuf root: $Protobuf_ROOT"
    
    # Double-check we're using the right cmake version
    local cmake_version=$(cmake --version | head -n1 | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' | head -n1)
    if [[ "$cmake_version" != "$CMAKE_VERSION" ]]; then
        error "Wrong CMake version detected: $cmake_version (expected $CMAKE_VERSION)"
        error "PATH: $PATH"
        error "which cmake: $(which cmake)"
        error "Custom cmake: $DEPS_DIR/install/cmake/bin/cmake"
        error "Custom cmake version: $($DEPS_DIR/install/cmake/bin/cmake --version | head -n1)"
        
        # Try using the full path directly
        warning "Attempting to use full path to cmake binary"
        export CMAKE_COMMAND="$DEPS_DIR/install/cmake/bin/cmake"
        log "Set CMAKE_COMMAND to: $CMAKE_COMMAND"
    fi
}

# Run the original midigpt setup script
run_original_setup() {
    if [[ ! -f "midigpt_setup_helper.sh" ]]; then
        error "midigpt_setup_helper.sh not found in current directory"
        error "Please make sure you're running this script from the directory containing midigpt_setup_helper.sh"
        exit 1
    fi
    
    log "Running original midigpt setup with custom dependencies..."
    log "Repository will be set up in: $REPO_DIR"
    log "Arguments: $SETUP_ARGS"
    
    # Clean up any existing protobuf build artifacts that might conflict
    if [[ -d "$REPO_DIR/MIDI-GPT/libraries/protobuf/build" ]]; then
        log "Cleaning existing protobuf build artifacts..."
        rm -rf "$REPO_DIR/MIDI-GPT/libraries/protobuf/build"
    fi
    
    # Export our environment variables so they're available to the child process
    export PATH CMAKE_PREFIX_PATH Protobuf_ROOT Protobuf_DIR PKG_CONFIG_PATH CMAKE_COMMAND
    if [[ "$OSTYPE" == "darwin"* ]]; then
        export DYLD_LIBRARY_PATH
    else
        export LD_LIBRARY_PATH
    fi
    
    # Run the original setup script
    bash midigpt_setup_helper.sh $SETUP_ARGS
    
    if [[ $? -eq 0 ]]; then
        success "MidiGPT setup completed successfully with custom dependencies!"
    else
        error "MidiGPT setup failed"
        log "Troubleshooting tips:"
        log "1. Check that cmake and protoc are using the correct versions:"
        log "   cmake --version (should be 3.23.1)"
        log "   protoc --version (should be 3.12.3)"
        log "2. Try cleaning and rebuilding:"
        log "   rm -rf $REPO_DIR"
        log "   ./setup_midigpt_with_custom_deps.sh $SETUP_ARGS"
        exit 1
    fi
}

# Create a script to reuse the environment later
create_env_script() {
    local env_script="$DEPS_DIR/setup_env.sh"
    
    log "Creating environment setup script for future use..."
    
    cat > "$env_script" << EOF
#!/bin/bash
# MidiGPT Dependencies Environment Setup
# Source this file to use the custom cmake and protobuf versions

# Set paths for our custom cmake and protobuf
# Remove any existing cmake/protobuf paths to avoid conflicts
export PATH=\$(echo "\$PATH" | tr ':' '\n' | grep -v cmake | grep -v protobuf | tr '\n' ':' | sed 's/:\$//')
export PATH="$DEPS_DIR/install/cmake/bin:$DEPS_DIR/install/protobuf/bin:\$PATH"
export CMAKE_PREFIX_PATH="$DEPS_DIR/install/protobuf:\$CMAKE_PREFIX_PATH"
export Protobuf_ROOT="$DEPS_DIR/install/protobuf"
export Protobuf_DIR="$DEPS_DIR/install/protobuf/lib/cmake/protobuf"
export PKG_CONFIG_PATH="$DEPS_DIR/install/protobuf/lib/pkgconfig:\$PKG_CONFIG_PATH"

# Add protobuf lib to library path
if [[ "\$OSTYPE" == "darwin"* ]]; then
    export DYLD_LIBRARY_PATH="$DEPS_DIR/install/protobuf/lib:\$DYLD_LIBRARY_PATH"
else
    export LD_LIBRARY_PATH="$DEPS_DIR/install/protobuf/lib:\$LD_LIBRARY_PATH"
fi

# Fallback: set CMAKE_COMMAND to full path if which cmake doesn't work
if ! command -v cmake &> /dev/null || [[ "\$(cmake --version | head -n1)" != *"3.23.1"* ]]; then
    export CMAKE_COMMAND="$DEPS_DIR/install/cmake/bin/cmake"
    echo "Warning: Using CMAKE_COMMAND fallback: \$CMAKE_COMMAND"
fi

echo "Environment configured for MidiGPT custom dependencies:"
echo "  CMake: \$(cmake --version | head -n1)"
echo "  Protobuf: \$(protoc --version)"
echo "  Protobuf root: \$Protobuf_ROOT"
echo "  CMake path: \$(which cmake)"
echo "  Protoc path: \$(which protoc)"
EOF
    
    chmod +x "$env_script"
    success "Environment script created at $env_script"
    log "In future terminal sessions, run: source $env_script"
}

# Main execution
main() {
    log "Starting MidiGPT setup with custom dependencies..."
    log "Will install CMake $CMAKE_VERSION and Protobuf $PROTOBUF_VERSION"
    log "Installation directory: $DEPS_DIR"
    
    detect_os
    setup_directories
    download_cmake
    download_build_protobuf
    setup_environment
    create_env_script
    run_original_setup
    
    echo
    success "Complete! MidiGPT is now set up with custom cmake and protobuf versions."
    success "Repository location: ./$REPO_DIR"
    echo
    warning "For future sessions, remember to source the environment:"
    echo "  source $DEPS_DIR/setup_env.sh"
}

# Run main function
main "$@"