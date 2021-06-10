import subprocess
import pathlib
import time
import os
import json
from base64 import b64decode
from google.protobuf.json_format import MessageToJson
import uuid
import qrcode
import logging


from payments.price_feed import get_btc_value
import config


class lnd:
    def __init__(self):
        from lndgrpc import LNDClient

        # Copy admin macaroon and tls cert to local machine
        self.copy_certs()

        # Conect to lightning node
        connection_str = "{}:{}".format(config.host, config.lnd_rpcport)
        logging.info(
            "Attempting to connect to lightning node {}. This may take a few seconds...".format(
                connection_str
            )
        )

        for i in range(config.connection_attempts):
            try:
                logging.info("Attempting to initialise lnd rpc client...")
                time.sleep(3)
                self.lnd = LNDClient(
                    "{}:{}".format(config.host, config.lnd_rpcport),
                    macaroon_filepath=self.certs["macaroon"],
                    cert_filepath=self.certs["tls"],
                )

                if "invoice" in self.certs["macaroon"]:
                    logging.info("Testing we can fetch invoices...")
                    inv, _ = self.create_lnd_invoice(1)
                    logging.info(inv)
                else:
                    logging.info("Getting lnd info...")
                    info = self.lnd.get_info()
                    logging.info(info)

                logging.info("Successfully contacted lnd.")
                break

            except Exception as e:
                logging.error(e)
                time.sleep(config.pollrate)
                logging.info(
                    "Attempting again... {}/{}...".format(
                        i + 1, config.connection_attempts
                    )
                )
        else:
            raise Exception(
                "Could not connect to lnd. Check your gRPC / port tunneling settings and try again."
            )

        logging.info("Ready for payments requests.")
        return

    def create_qr(self, uuid, address, value):
        qr_str = "{}".format(address.upper())
        img = qrcode.make(qr_str)
        img.save("static/qr_codes/{}.png".format(uuid))
        return

    # Copy tls and macaroon certs from remote machine.
    def copy_certs(self):
        # self.certs = {'tls' : os.path.expanduser(config.lnd_cert),
        #               'macaroon' : os.path.expanduser(config.lnd_macaroon)}
        self.certs = {'tls' : config.lnd_cert,
                      'macaroon' : config.lnd_macaroon}
        # print(os.listdir(os.path.dirname(os.path.expanduser(config.lnd_cert))))
        # print("Found tls.cert and admin.macaroon.")
        print(self.certs)
        print(os.listdir("/"))
        return

    # Create lightning invoice
    def create_lnd_invoice(self, btc_amount, memo=None, description_hash=None):
        # Multiplying by 10^8 to convert to satoshi units
        sats_amount = int(btc_amount * 10 ** 8)
        res = self.lnd.add_invoice(
            value=sats_amount, memo=memo, description_hash=description_hash
        )
        lnd_invoice = json.loads(MessageToJson(res))

        return lnd_invoice["paymentRequest"], lnd_invoice["rHash"]

    def get_address(self, amount, label):
        address, r_hash = self.create_lnd_invoice(amount, memo=label)
        return address, r_hash

    def pay_invoice(self, invoice):
        ret = json.loads(
            MessageToJson(self.lnd.send_payment(invoice, fee_limit_msat=20 * 1000))
        )
        logging.info(ret)
        return

    # Check whether the payment has been paid
    def check_payment(self, rhash):
        invoice_status = json.loads(
            MessageToJson(self.lnd.lookup_invoice(r_hash_str=b64decode(rhash).hex()))
        )

        if "amtPaidSat" not in invoice_status.keys():
            conf_paid = 0
            unconf_paid = 0
        else:
            # Store amount paid and convert to BTC units
            conf_paid = int(invoice_status["amtPaidSat"]) / (10 ** 8)
            unconf_paid = 0

        return conf_paid, unconf_paid
