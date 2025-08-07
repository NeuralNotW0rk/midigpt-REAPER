root_path=$(pwd)
reaper_resource_path=~/Library/Application\ Support/REAPER

ln -sf "$root_path/src/Scripts/composers_assistant_v2" "$reaper_resource_path/Scripts"
ln -sf "$root_path/src/Effects/composers_assistant_v2" "$reaper_resource_path/Effects"

env_path=$root_path/.venv

rm -r $env_path
python3.9 -m venv $env_path
source $env_path/bin/activate

python3 -m pip install --upgrade pip
pip install -r requirements.txt

