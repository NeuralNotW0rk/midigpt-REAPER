src_path=$(pwd)/src
reaper_resource_path=~/Library/Application\ Support/REAPER

ln -sf "$src_path/Scripts/composers_assistant_v2" "$reaper_resource_path/Scripts"
ln -sf "$src_path/Effects/composers_assistant_v2" "$reaper_resource_path/Effects"

rm -r .venv
python3.9 -m venv .venv
source .venv/bin/activate

python3 -m pip install --upgrade pip
pip install -r requirements.txt

