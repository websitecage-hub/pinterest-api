from Crypto.Cipher import AES
import base64, json, execjs, time, binascii

class Utils:
    @staticmethod
    def dict_to_list(data: dict) -> list:
        result=[]
        for obj in data:
            result.append(data[obj])

        return result
    
class Arkose:
    @staticmethod
    def generate_key(ctx:execjs.compile, s_value:str, useragent:str) -> list:
        key=Utils.dict_to_list(ctx.call(
            'genkey',
            useragent,
            s_value
        ))
        return key

    @staticmethod
    def x_ark_value() -> str:
        now=int(time.time())
        return str(now - (now % 21600))

def main():
    test=base64.b64decode(input("Bda: ").encode())
    res=json.loads(test)
    ctx = execjs.compile(open("arkose.js").read())
    key=bytes(Arkose.generate_key(
        ctx, 
        res["s"],
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36{Arkose.x_ark_value()}"
    ))
    iv=binascii.unhexlify(res["iv"])
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decryptedtext = cipher.decrypt(base64.b64decode(res["ct"]))
    print(decryptedtext.decode())

if __name__ =='__main__':
    main()