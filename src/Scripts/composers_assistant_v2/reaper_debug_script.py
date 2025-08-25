# Run this in REAPER to debug import issues
from reaper_python import *
import sys

def patch_stdout_stderr_open():
    class ReaperConsole:
        def write(self, output):
            RPR_ShowConsoleMsg(output)
        def flush(self):
            pass
        def close(self):
            pass
    
    reaper_console = ReaperConsole()
    sys.stdout = reaper_console
    sys.stderr = reaper_console

patch_stdout_stderr_open()

def debug_imports():
    print("=== IMPORT DEBUG STARTING ===")
    RPR_ClearConsole()
    
    print("Python path:")
    for path in sys.path[:3]:
        print("  " + path)
    
    print("")
    print("1. Testing basic imports...")
    
    try:
        print("Testing rpr_ca_functions...")
        import rpr_ca_functions as fn
        print("OK: rpr_ca_functions imported successfully")
        
        print("Testing fn.get_global_options...")
        try:
            options = fn.get_global_options()
            print("OK: fn.get_global_options works")
        except Exception as e:
            print("ERROR: fn.get_global_options failed: " + str(e))
        
    except ImportError as e:
        print("ERROR: Failed to import rpr_ca_functions: " + str(e))
        return False
    except Exception as e:
        print("ERROR: Error with rpr_ca_functions: " + str(e))
    
    print("")
    print("2. Testing rpr_midigpt_functions import...")
    try:
        print("Attempting import...")
        import rpr_midigpt_functions as midigpt_fn
        print("OK: rpr_midigpt_functions imported successfully")
        
        if hasattr(midigpt_fn, 'get_midigpt_global_options'):
            print("OK: get_midigpt_global_options found")
        else:
            print("ERROR: get_midigpt_global_options NOT found")
        
        if hasattr(midigpt_fn, 'get_global_options'):
            print("OK: get_global_options found")
        else:
            print("ERROR: get_global_options NOT found")
            
        if hasattr(midigpt_fn, 'test_function'):
            result = midigpt_fn.test_function()
            print("OK: Test function result: " + str(result))
        
    except ImportError as e:
        print("ERROR: Failed to import rpr_midigpt_functions: " + str(e))
        print("This means the file does not exist or has syntax errors")
        return False
    except SyntaxError as e:
        print("ERROR: Syntax error in rpr_midigpt_functions: " + str(e))
        return False
    except Exception as e:
        print("ERROR: Other error with rpr_midigpt_functions: " + str(e))
        return False
    
    print("")
    print("3. Testing midigpt function calls...")
    try:
        global_options = midigpt_fn.get_midigpt_global_options()
        print("OK: get_midigpt_global_options works")
    except Exception as e:
        print("ERROR: get_midigpt_global_options failed: " + str(e))
    
    print("")
    print("=== IMPORT DEBUG COMPLETE ===")
    return True

if __name__ == '__main__':
    debug_imports()

RPR_Undo_OnStateChange('Import_Debug')