"""Revalidate selected account keys and exact client build before each decode."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from recipient import require_supported, validate_keys, require_local_validation


def main():
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--wechat-app',type=Path,required=True)
    parser.add_argument('--wechat-version',required=True)
    parser.add_argument('--wechat-build',required=True)
    parser.add_argument('--validation-config',type=Path)
    known,rest=parser.parse_known_args()
    probe=argparse.ArgumentParser(add_help=False)
    probe.add_argument('--db-base',type=Path,required=True);probe.add_argument('--keys',type=Path,required=True)
    paths,_=probe.parse_known_args(rest)
    version,build=require_supported(known.wechat_app)
    if (version,build)!=(known.wechat_version,known.wechat_build):
        raise ValueError('微信已更新，采集暂停。请重新配置并验证。')
    keys=validate_keys(paths.db_base,json.loads(paths.keys.read_text()))
    config=json.loads(known.validation_config.read_text()) if known.validation_config else {}
    # The receipt must match the actual decoder arguments, not only stored paths.
    config={**config, 'wechat_version':[version,build]}
    require_local_validation(config,paths.db_base,keys)
    from scripts.local_vault_decoder import main as decode
    sys.argv=[sys.argv[0],*rest];decode()

if __name__=='__main__':
    try:main()
    except Exception:
        print('解码前校验未通过。请检查微信版本、新增消息分片及密钥，停止服务后重新配置。',file=sys.stderr)
        sys.exit(1)
