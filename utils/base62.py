
class Base62:
    ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    BASE = 62
    
    @staticmethod
    def encode(number: int) -> str:
        """Convert integer to Base62 string."""
        if number < 0:
            raise ValueError("Base62 cannot encode negative numbers")            
        if number == 0:
            return "0"
        
        result = []
        while number > 0:
            number, remainder = divmod(number, 62)
            result.append(Base62.ALPHABET[remainder])
        
        return "".join(reversed(result))
    
    @staticmethod
    def decode(string: str) -> int:
        """Convert Base62 string back to integer."""
        result = 0
        for char in string:
            if(char not in Base62.ALPHABET):
                raise ValueError(f"invalid Base62 character: {char}")
            result = result * 62 + Base62.ALPHABET.index(char)
        return result