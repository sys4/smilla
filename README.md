# smilla

smilla is a SMIMEA aware milter.

It implements
[draft-ietf-dane-smime](https://tools.ietf.org/wg/dane/draft-ietf-dane-smime/)
as specified by the [IETF DANE
WG](https://datatracker.ietf.org/wg/dane/charter/).

smilla is written in Python. It queries the SMIMEA-Record (Record-Type
53) in the DNS zone of the email recipient for an x509 certificate. If
such a record is found, it will encrypt the mail using the fetched
certificate.

The SMIMEA record for the x509 certificate must be created with SMIMEA options "3 0 0"
 * Certificate Usage 3 = DANE-EE (Domain-issued certificate)
 * Selector 0 = Cert (Full certificate)
 * Matching Type 0 = Full (No hash used) 

smilla is a joined effort between [sys4](https://sys4.de) and [Posteo.de](https://posteo.de).

