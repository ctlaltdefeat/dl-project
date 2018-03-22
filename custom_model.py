import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
from onmt.modules import GlobalAttention, MultiHeadedAttention

attn = GlobalAttention(512)
m_attn = MultiHeadedAttention(2, 512)

distinct_tokens = range(30)


class LipEncoder(nn.Module):
    def __init__(self):
        super(LipEncoder, self).__init__()
        self.gru = nn.GRU(input_size=512, hidden_size=256, num_layers=2, batch_first=True, bidirectional=True)
        self.conv1 = nn.Conv3d(in_channels=1, out_channels=128, kernel_size=(2, 3, 3), stride=2)
        self.bn1 = nn.BatchNorm3d(128)
        self.conv2 = nn.Conv3d(in_channels=128, out_channels=256, kernel_size=(2, 3, 3), stride=2)
        self.bn2 = nn.BatchNorm3d(256)
        self.conv3 = nn.Conv2d(in_channels=256, out_channels=512, kernel_size=(3, 3), stride=2)
        self.bn3 = nn.BatchNorm2d(512)
        self.conv4 = nn.Conv2d(in_channels=512, out_channels=512, kernel_size=(3, 3), stride=2)
        self.bn4 = nn.BatchNorm2d(512)
        self.conv5 = nn.Conv2d(in_channels=512, out_channels=512, kernel_size=(3, 3), stride=2)
        self.bn5 = nn.BatchNorm2d(512)
        self.fc1 = nn.Linear(7680, 512)

    def forward(self, x, lengths=None):
        x = x.squeeze(-1)
        x = F.leaky_relu(self.bn1(self.conv1(x)))
        x = F.leaky_relu(self.bn2(self.conv2(x)))
        lst = []
        for i in x:
            d = i.permute(1, 0, 2, 3)
            d = F.leaky_relu(self.bn3(self.conv3(d)))
            d = F.leaky_relu(self.bn4(self.conv4(d)))
            d = F.leaky_relu(self.bn5(self.conv5(d)))
            d = d.view(len(d), -1)
            d = self.fc1(d)
            lst.append(d)
        output, hidden = self.gru(torch.stack(lst))
        return output, hidden


class Speller(nn.Module):
    def __init__(self):
        super(Speller, self).__init__()
        # embedding not needed for char-level model:
        # self.vocab_to_hidden = nn.Embedding(, 1024)
        self.to_tokens = nn.Linear(512, len(distinct_tokens))
        self.gru = nn.GRU(input_size=len(distinct_tokens), hidden_size=512, num_layers=2, batch_first=True,
                          bidirectional=False)

    @staticmethod
    def to_one_hot(input_x, vocab_size=len(distinct_tokens)):
        if type(input_x) is Variable:
            input_x = input_x.data
        input_type = type(input_x)
        batch_size = input_x.size(0)
        time_steps = input_x.size(1)
        input_x = input_x.unsqueeze(2).type(torch.LongTensor)
        onehot_x = Variable(
            torch.LongTensor(batch_size, time_steps, vocab_size).zero_().scatter_(-1, input_x, 1)).type(input_type)
        return onehot_x

    def forward_step(self, input, decoder_hidden):
        gru_output, decoder_hidden = self.gru(input, decoder_hidden)
        return self.to_tokens(gru_output), decoder_hidden

    def forward(self, initial_decoder_hidden, targets, encoder_outputs, teacher_forced=True):
        # if teacher_forced:
        #     one_hot_target = self.to_one_hot(targets).type(torch.FloatTensor)
        #     output, last_hidden_state = self.gru(one_hot_target, initial_decoder_hidden)
        #     return self.to_tokens(output)
        decoder_hidden = initial_decoder_hidden
        input = self.to_one_hot(targets[:, [0]]).type(torch.FloatTensor)  # should always be <sos>
        outputs = []
        for timestep in range(targets.size()[1]):
            # output, decoder_hidden = self.gru(targets[:, [timestep], :], decoder_hidden)
            gru_output, decoder_hidden = self.gru(input, decoder_hidden)
            attn_output, attn_dist = attn(input=decoder_hidden.permute(1, 0, 2)[:, -1:, :],
                                          memory_bank=encoder_outputs)
            attn_output, attn_dist = attn_output.permute(1, 0, 2), attn_dist.permute(1, 0, 2)
            output_tokens = self.to_tokens(attn_output)
            outputs.append(output_tokens)
            # _, topi = output_tokens.data.topk(1, dim=2)
            # input = self.to_one_hot(topi.squeeze(0)).type(torch.FloatTensor)
            if teacher_forced:
                input = self.to_one_hot(targets[:, [timestep]]).type(torch.FloatTensor)
            else:
                input = output_tokens
        return torch.cat(outputs, dim=1)

    def decode(self, decoder_hidden, beam_width=6):
        # freely decode with beam search, returning top result
        return


class Combined(nn.Module):
    def __init__(self, enc, dec):
        super(Combined, self).__init__()
        # embedding not needed for char-level model:
        # self.vocab_to_hidden = nn.Embedding(, 1024)
        self.enc = enc
        self.dec = dec

    def forward(self, lips, targets):
        enc_out, enc_hidden = self.enc(lips)
        return self.dec(Combined.encoder_hidden_to_decoder_hidden(enc_hidden), targets, enc_out)

    @staticmethod
    def encoder_hidden_to_decoder_hidden(encoder_hidden):
        return encoder_hidden.permute(1, 0, 2).view(encoder_hidden.size()[1], 2, -1).permute(1, 0, 2)


com = Combined(LipEncoder(), Speller())
criterion = nn.CrossEntropyLoss()
optim = torch.optim.Adam(com.parameters(), lr=1e-4)
print(com(Variable(torch.randn(1, 1, 120, 220, 150)), torch.LongTensor([1, 2, 3]).unsqueeze(0)))
# for lips, targets in range(0, 5):
#     optim.zero_grad()
#     pred = com(lips, targets)
#     loss = criterion(pred.permute(0, 2, 1), targets)
#     loss.backward()
#     optim.step()