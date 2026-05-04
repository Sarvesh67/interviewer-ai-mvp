import re

class StringUtils:
    
    @staticmethod
    def looks_like_uuid(val) -> bool:
        if not isinstance(val, str):
            return False
        return bool(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", val))