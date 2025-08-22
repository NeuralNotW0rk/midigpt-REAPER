root_path=$(pwd)

env_path=$root_path/.venv

rm -r $env_path
python3.9 -m venv $env_path
source $env_path/bin/activate

python3 -m pip install --upgrade pip
pip install -r requirements.txt


reaper_resource_path=~/Library/Application\ Support/REAPER

ln -sf "$root_path/src/Scripts/composers_assistant_v2" "$reaper_resource_path/Scripts"
ln -sf "$root_path/src/Effects/composers_assistant_v2" "$reaper_resource_path/Effects"

release_version=2.1.0
zip_name=composers.assistant.v.$release_version.zip
model_dir=Scripts/composers_assistant_v2/models_permuted_labels

mkdir temp
cd temp
curl -L -O https://github.com/m-malandro/composers-assistant-REAPER/releases/download/v$release_version/$zip_name
unzip $zip_name
cp -a $model_dir/. ../src/$model_dir
cd ..
rm -r temp


